{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE DerivingStrategies #-}

-- LLM-driven atomic fact extraction from markdown.
-- Replaces scripts/info_density.py — same logic, Haskell-native.
module HaskellTester.Evaluation.FactExtract
    ( Fact (..)
    , extractFacts
    , computeNetNew
    , DensityReport (..)
    , buildReport
    ) where

import Control.Exception (catch, SomeException)
import qualified Data.Aeson as A
import qualified Data.Aeson.Types as A (parseMaybe)
import qualified Data.Aeson.KeyMap as KM
import qualified Data.ByteString.Lazy as BL
import qualified Data.ByteString.Lazy.Char8 as BLC
import qualified Data.Map.Strict as Map
import qualified Data.Set as Set
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import qualified Data.Text.IO as TIO
import qualified Data.Vector as V
import GHC.Generics (Generic)
import System.Environment (lookupEnv)

import HaskellTester.LLM.Deepseek


data Fact = Fact
    { factCategory :: Text
    , factClaim    :: Text
    }
    deriving stock (Eq, Show, Generic)

instance A.FromJSON Fact where
    parseJSON = A.withObject "Fact" $ \o -> Fact
        <$> o A..: "category"
        <*> o A..: "claim"


-- Extract atomic facts from a markdown document. Caps input at 12k chars.
extractFacts :: Text -> IO [Fact]
extractFacts md = do
    mKey <- lookupEnv "DEEPSEEK_API_KEY"
    case mKey of
        Nothing  -> pure []
        Just key -> tryExtract (T.pack key) md 0
  where
    tryExtract key m attempt
        | attempt >= 3 = pure []
        | otherwise = (doExtract key m) `catch` \(_ :: SomeException) ->
            tryExtract key m (attempt + 1)

    doExtract key m = do
        let prompt = extractPrompt <> T.take 12000 m
                  <> "\n\nIMPORTANT: produce VALID JSON. Close all brackets and commas."
        let req = (defaultRequest [Message "user" prompt])
                { reqMaxTokens = 4000, reqTemperature = 0.0 }
        reply <- callChat key req
        case parseFactsReply reply of
            Just fs -> pure fs
            Nothing -> pure []


extractPrompt :: Text
extractPrompt = T.unlines
    [ "Extract every ATOMIC, VERIFIABLE fact about the binary from the markdown below."
    , ""
    , "Rules:"
    , "- Each fact is ONE concrete claim: \"binary accepts --help\", \"exit code is 0 on success\""
    , "- Skip marketing / promotional / cross-reference content (\"see online docs\", \"try it online\")"
    , "- Skip historical/licensing/contributor content"
    , "- Categorize: cli_flags, io_model, exit_codes, error_grammar, behavior, identity, other"
    , ""
    , "Reply with strict JSON only:"
    , "{\"facts\": [{\"category\":\"<cat>\",\"claim\":\"<one short claim>\"},...]}"
    , ""
    , "Markdown:"
    , "---"
    ]


parseFactsReply :: Text -> Maybe [Fact]
parseFactsReply raw =
    let txt = extractJson raw
    in case A.decode (BL.fromStrict (TE.encodeUtf8 txt)) of
        Just (A.Object o) -> case KM.lookup "facts" o of
            Just (A.Array v) ->
                Just [ f | Just f <- map (A.parseMaybe A.parseJSON) (V.toList v) ]
            _ -> Nothing
        _ -> Nothing
  where
    extractJson t = T.dropWhileEnd (/= '}') (T.dropWhile (/= '{') t)


-- Given belief and README facts, return (net_new, overlap).
-- LLM-based semantic dedup with strict criteria.
computeNetNew :: [Fact] -> [Fact] -> IO ([Fact], [Fact])
computeNetNew beliefFacts readmeFacts = do
    mKey <- lookupEnv "DEEPSEEK_API_KEY"
    case mKey of
        Nothing -> pure (beliefFacts, [])
        Just key -> do
            let prompt = mkDedupPrompt beliefFacts readmeFacts
            let req = (defaultRequest [Message "user" prompt])
                    { reqMaxTokens = 1500, reqTemperature = 0.0 }
            reply <- callChat (T.pack key) req `catch` \(_ :: SomeException) -> pure ""
            let coveredIdx = parseCoveredIdx reply
            let indexedBelief = zip [0 :: Int ..] beliefFacts
            let overlap = [f | (i, f) <- indexedBelief, i `Set.member` coveredIdx]
            let netNew  = [f | (i, f) <- indexedBelief, not (i `Set.member` coveredIdx)]
            pure (netNew, overlap)
  where
    parseCoveredIdx raw =
        let txt = T.dropWhileEnd (/= '}') (T.dropWhile (/= '{') raw)
        in case A.decode (BL.fromStrict (TE.encodeUtf8 txt)) of
            Just (A.Object o) -> case KM.lookup "covered" o of
                Just (A.Array v) -> Set.fromList
                    [ truncate n | A.Number n <- V.toList v ]
                _ -> Set.empty
            _ -> Set.empty


mkDedupPrompt :: [Fact] -> [Fact] -> Text
mkDedupPrompt belief readme = T.unlines
    [ "Given facts from a README and from an agent's belief, decide for EACH belief fact"
    , "whether it is GENUINELY covered by the README facts."
    , ""
    , "STRICT CRITERIA — a belief fact is 'covered' ONLY IF:"
    , "  - The README fact asserts the EXACT SAME specific claim, not just an abstract category."
    , "  - An ABSTRACT README claim like 'tool transforms JSON' does NOT cover a SPECIFIC belief"
    , "    claim like 'outputs 1 on input {\"a\":1} with filter .a' — these are different levels"
    , "    of detail and the specific fact should count as NEW."
    , "  - A specific README claim (e.g. 'accepts --json flag') covers a belief claim that repeats it."
    , ""
    , "Bias: when in doubt, mark NOT covered. We are measuring genuinely new operational facts."
    , ""
    , "README facts:"
    , T.intercalate "\n" ["- " <> factClaim f | f <- readme]
    , ""
    , "Belief facts (indexed):"
    , T.intercalate "\n" ["[" <> T.pack (show i) <> "] " <> factClaim f
                        | (i :: Int, f) <- zip [0..] belief]
    , ""
    , "Reply with strict JSON: {\"covered\": [<list of indices of covered belief facts>]}"
    ]


data DensityReport = DensityReport
    { drReadmeFacts :: Int
    , drBeliefFacts :: Int
    , drOverlap     :: Int
    , drNetNew      :: Int
    , drNewPercent  :: Double
    , drNetNewByCategory :: Map.Map Text [Fact]
    }
    deriving stock Show


buildReport :: FilePath -> FilePath -> IO DensityReport
buildReport readmePath beliefPath = do
    readme <- TIO.readFile readmePath
    belief <- TIO.readFile beliefPath
    readmeFacts <- extractFacts readme
    beliefFacts <- extractFacts belief
    (netNew, overlap) <- computeNetNew beliefFacts readmeFacts
    let beliefTotal = length beliefFacts
    let pct = if beliefTotal == 0 then 0
              else 100 * fromIntegral (length netNew) / fromIntegral beliefTotal
    let byCat = Map.fromListWith (++)
                  [(factCategory f, [f]) | f <- netNew]
    pure DensityReport
        { drReadmeFacts = length readmeFacts
        , drBeliefFacts = beliefTotal
        , drOverlap     = length overlap
        , drNetNew      = length netNew
        , drNewPercent  = pct
        , drNetNewByCategory = byCat
        }
