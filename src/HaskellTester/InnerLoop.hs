{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE DerivingStrategies #-}

-- LLM-driven inner loop: probe → hypothesize → verify → repeat.
--
-- On each round the LLM is given:
--   - the playbook section relevant to the current archetype
--   - the knowledge base so far (probe history, verified / rejected hypotheses)
--   - a request for the next action: PROBE, VERIFY, or STOP
--
-- The agent executes the chosen action, updates state, and loops until the LLM
-- signals STOP or maxRounds is exceeded.
module HaskellTester.InnerLoop
    ( InnerLoopConfig (..)
    , InnerLoopState (..)
    , KnowledgeBase (..)
    , Hypothesis (..)
    , AgentAction (..)
    , defaultConfig
    , initialState
    , emptyKB
    , runInnerLoop
    , runInnerLoopFrom   -- seedable variant for baseline injection
    , buildLoopPrompt    -- exposed for tests
    , parseAction        -- exposed for tests
    ) where

import Control.Exception (catch, SomeException)
import Control.Monad (foldM)
import qualified Data.Aeson as A
import qualified Data.Aeson.KeyMap as KM
import qualified Data.ByteString.Lazy as BL
import Data.Maybe (mapMaybe)
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import qualified Data.Vector as V
import System.Environment (lookupEnv)

import HaskellTester.LLM.Deepseek
import HaskellTester.Playbook
import HaskellTester.Probe.Shell
import HaskellTester.Types


--------------------------------------------------------------------------------
-- State + config

data InnerLoopConfig = InnerLoopConfig
    { cfgMaxRounds  :: Int      -- safety cap on iterations
    , cfgTargetBin  :: FilePath -- path to the black-box binary
    }
    deriving (Show)

defaultConfig :: FilePath -> InnerLoopConfig
defaultConfig bin = InnerLoopConfig
    { cfgMaxRounds = 15
    , cfgTargetBin = bin
    }


data KnowledgeBase = KnowledgeBase
    { kbFacts        :: [Text]            -- terse facts agent has accumulated
    , kbProbeHistory :: [(Text, Text)]    -- (cmd line, output snippet)
    , kbVerified     :: [Hypothesis]
    , kbRejected     :: [Hypothesis]
    }
    deriving (Show)


emptyKB :: KnowledgeBase
emptyKB = KnowledgeBase [] [] [] []


data Hypothesis = Hypothesis
    { hClaim  :: Text   -- e.g. "binary accepts --json flag"
    , hOracle :: Text   -- e.g. "./executable --json | head -1 starts with '{'"
    }
    deriving (Show, Eq)


data InnerLoopState = InnerLoopState
    { ilsRound  :: Int
    , ilsKB     :: KnowledgeBase
    , ilsStopped :: Maybe Text  -- reason if loop has stopped
    }
    deriving (Show)


initialState :: InnerLoopState
initialState = InnerLoopState 0 emptyKB Nothing


--------------------------------------------------------------------------------
-- Action protocol (LLM-emitted)

-- One belief grounded in an actually-executed probe.
data Finding = Finding
    { fClaim    :: Text   -- e.g. "binary version is jq-1.7.1-apple"
    , fEvidence :: Text   -- substring that must match a real probe cmd in history
    }
    deriving (Show, Eq)


data AgentAction
    = ProbeAction  Text [Text] Text               -- cmd, args, stdin (empty if none)
    | VerifyAction Hypothesis Text [Text] Text    -- hypothesis, cmd, args, stdin
    | StopAction   Text [Finding]                 -- LLM-decided stop with reason + grounded findings
    | ParseFailed  Text                           -- could not parse LLM reply
    deriving (Show)


--------------------------------------------------------------------------------
-- Prompt building

-- Strip a single playbook to only the sections that matter for the inner loop.
relevantSections :: Playbook -> Text
relevantSections pb = T.unlines $ concatMap fetch
    [ "Probe layer", "Hypothesize patterns", "Verify layer"
    , "Stop conditions", "Common pitfalls" ]
  where
    fetch heading = case extractSection heading pb of
        Just body -> ["## " <> heading, body, ""]
        Nothing   -> []


buildLoopPrompt :: Playbook -> InnerLoopState -> InnerLoopConfig -> [Message]
buildLoopPrompt pb st cfg =
    [ Message "system"
        ("You are driving a black-box test agent. The target binary is at "
         <> T.pack (cfgTargetBin cfg) <> ".\n\n"
         <> "Use the following playbook to guide your probing strategy:\n\n"
         <> relevantSections pb
         <> "\n\nEach round you must emit ONE action as strict JSON. Use stdin to FEED INPUT — do NOT use shell pipes:\n"
         <> "  {\"action\":\"probe\",\"cmd\":\"<bin>\",\"args\":[\"--help\"],\"stdin\":\"\"}\n"
         <> "  {\"action\":\"probe\",\"cmd\":\"<bin>\",\"args\":[\".a\"],\"stdin\":\"{\\\"a\\\":1}\"}     <-- feed JSON via stdin field, NOT via 'echo X |'\n"
         <> "  {\"action\":\"verify\",\"claim\":\"<...>\",\"cmd\":\"<bin>\",\"args\":[...],\"stdin\":\"<input>\",\"expect_contains\":\"<...>\"}\n"
         <> "  {\"action\":\"stop\",\"reason\":\"<...>\",\"findings\":[\n"
         <> "      {\"claim\":\"binary version is X\",\"evidence\":\"--version\"},\n"
         <> "      {\"claim\":\"...\",\"evidence\":\"<cmd substring from history>\"}\n"
         <> "  ]}\n\n"
         <> "ANTI-HALLUCINATION RULE: every finding's evidence MUST be a substring of a command\n"
         <> "you actually ran in this loop (see 'commands already executed' below). If you cannot\n"
         <> "ground a fact in real probe history, DO NOT include it. A stop with unverifiable\n"
         <> "findings will be rejected and you will be forced to probe more.\n\n"
         <> "Reply with JSON only, no preamble."
        )
    , Message "user" (renderState st)
    ]


renderState :: InnerLoopState -> Text
renderState st = T.unlines $ concat
    [ [ "Round: " <> tshow (ilsRound st) ]
    , [ "" ]
    , [ "ALL commands already executed (do NOT repeat any of these — pick something different):" ]
    , map ("  - " <>) (uniqueCmds (kbProbeHistory (ilsKB st)))
    , [ "" ]
    , [ "Latest probe output (most recent first, last 3 only):" ]
    , [ "  $ " <> cmd <> "\n    -> " <> T.take 150 out
      | (cmd, out) <- take 3 (kbProbeHistory (ilsKB st)) ]
    , [ "" ]
    , [ "Verified hypotheses: " <> tshow (length (kbVerified (ilsKB st))) ]
    , [ "  - " <> hClaim h | h <- take 5 (kbVerified (ilsKB st)) ]
    , [ "Rejected hypotheses: " <> tshow (length (kbRejected (ilsKB st))) ]
    , [ "" ]
    , [ "Decide the next action. If you've covered the playbook's stop conditions, emit STOP." ]
    , [ "If the command set above is already broad, prefer 'verify' or 'stop' over more 'probe'." ]
    ]
  where
    tshow x = T.pack (show x)

    -- Deduplicate by command line so the LLM sees the full set explored.
    uniqueCmds :: [(Text, Text)] -> [Text]
    uniqueCmds = foldr (\(cmd, _) acc -> if cmd `elem` acc then acc else cmd : acc) []


--------------------------------------------------------------------------------
-- Action parsing

parseAction :: Text -> AgentAction
parseAction raw =
    case A.decode (BL.fromStrict (TE.encodeUtf8 (extractJson raw))) of
        Just (A.Object o) ->
            case KM.lookup "action" o of
                Just (A.String "probe") ->
                    case (lookupString "cmd" o, lookupArray "args" o) of
                        (Just c, Just as) -> ProbeAction c as (lookupStringOr "stdin" o "")
                        _ -> ParseFailed "probe missing cmd/args"
                Just (A.String "verify") ->
                    case ( lookupString "cmd" o, lookupArray "args" o
                         , lookupString "claim" o, lookupString "expect_contains" o ) of
                        (Just c, Just as, Just claim, Just expect) ->
                            VerifyAction (Hypothesis claim ("stdout contains: " <> expect))
                                         c as (lookupStringOr "stdin" o "")
                        _ -> ParseFailed "verify missing fields"
                Just (A.String "stop") ->
                    let reason = case lookupString "reason" o of
                                    Just r  -> r
                                    Nothing -> "(no reason)"
                        findings = case KM.lookup "findings" o of
                                    Just (A.Array v) -> mapMaybe parseFinding (toList v)
                                    _                -> []
                    in StopAction reason findings
                _ -> ParseFailed "unknown action"
        _ -> ParseFailed ("could not parse JSON: " <> T.take 120 raw)
  where
    extractJson t = T.dropWhileEnd (/= '}') (T.dropWhile (/= '{') t)

    lookupString k o = case KM.lookup k o of
        Just (A.String t) -> Just t
        _                 -> Nothing

    lookupStringOr k o dflt = maybe dflt id (lookupString k o)

    lookupArray k o = case KM.lookup k o of
        Just (A.Array v)  -> Just (map valToText (toList v))
        _                 -> Nothing
      where
        valToText (A.String t) = t
        valToText other        = T.pack (show other)

    toList = V.toList

    parseFinding (A.Object o) = do
        A.String claim    <- KM.lookup "claim" o
        A.String evidence <- KM.lookup "evidence" o
        pure (Finding claim evidence)
    parseFinding _ = Nothing


-- Map LLM-emitted reply text to AgentAction. If the LLM call itself failed,
-- treat as a soft stop.
parseFromLLM :: Either Text Text -> AgentAction
parseFromLLM (Left err)  = StopAction ("LLM call failed: " <> err) []
parseFromLLM (Right txt) = parseAction txt


--------------------------------------------------------------------------------
-- Action execution

executeAction :: InnerLoopConfig -> AgentAction -> InnerLoopState -> IO InnerLoopState
executeAction cfg act st = case act of
    StopAction r findings ->
        let history    = map fst (kbProbeHistory (ilsKB st))
            grounded   = filter (\f -> any (fEvidence f `T.isInfixOf`) history) findings
            ungrounded = filter (\f -> not (any (fEvidence f `T.isInfixOf`) history)) findings
        in case ungrounded of
             []  ->  -- all findings grounded, accept stop
                 pure st
                   { ilsStopped = Just r
                   , ilsKB = (ilsKB st)
                       { kbFacts = map fClaim grounded ++ kbFacts (ilsKB st) }
                   }
             us  ->  -- at least one ungrounded finding: reject stop, force more probing
                 let feedback = "STOP REJECTED — findings not grounded in probe history: "
                              <> T.intercalate "; "
                                   [ "claim=\"" <> fClaim f <> "\" evidence=\"" <> fEvidence f <> "\""
                                   | f <- us ]
                              <> ". Either probe to verify these claims, or remove them and stop with only grounded findings."
                 in pure st
                      { ilsKB = (ilsKB st)
                          { kbProbeHistory =
                              ("(stop validator)", feedback) : kbProbeHistory (ilsKB st)
                          }
                      }

    ParseFailed reason ->
        pure st { ilsStopped = Just ("agent reply unparseable: " <> reason) }

    ProbeAction cmd args stdin' -> do
        let resolved = resolveCmd cfg cmd
        let stdinTag = if T.null stdin' then "" else " <" <> T.take 30 stdin' <> ">"
        let entry0   = T.pack resolved <> " " <> T.unwords args <> stdinTag
        let prior    = map fst (kbProbeHistory (ilsKB st))
        -- Defend against the LLM looping on the same command — refuse to re-execute,
        -- record the rejection so the LLM sees we already tried.
        if entry0 `elem` prior
            then pure st { ilsKB = (ilsKB st)
                            { kbProbeHistory =
                                (entry0, "(skipped: already executed)") : kbProbeHistory (ilsKB st) } }
            else do
                result <- runProbeWithStdin (T.unpack stdin') resolved (map T.unpack args)
                let entry = (prCmd result <> stdinTag, prStdout result <> "\n[stderr] " <> prStderr result)
                pure st { ilsKB = (ilsKB st) { kbProbeHistory = entry : kbProbeHistory (ilsKB st) } }

    VerifyAction hypothesis cmd args stdin' -> do
        result <- runProbeWithStdin (T.unpack stdin') (resolveCmd cfg cmd) (map T.unpack args)
        let ok = expectedIn hypothesis (prStdout result)
        let entry = (prCmd result, prStdout result)
        let kb    = ilsKB st
        let kb'   = kb
                  { kbProbeHistory = entry : kbProbeHistory kb
                  , kbVerified     = if ok then hypothesis : kbVerified kb else kbVerified kb
                  , kbRejected     = if ok then kbRejected kb else hypothesis : kbRejected kb
                  }
        pure st { ilsKB = kb' }
  where
    expectedIn h out =
        let needle = T.drop (T.length "stdout contains: ") (hOracle h)
        in needle `T.isInfixOf` out

    -- Allow LLM to say "<bin>" or pass an empty/relative cmd; default to target.
    resolveCmd cfg' c
        | T.null c || c == "<bin>" || c == "./executable" = cfgTargetBin cfg'
        | otherwise = T.unpack c


--------------------------------------------------------------------------------
-- The loop

runInnerLoop
    :: InnerLoopConfig -> Playbook -> IO (InnerLoopState, Maybe Text)
runInnerLoop cfg pb = runInnerLoopFrom cfg pb initialState


-- Variant that lets the caller seed the knowledge base (e.g. with baseline
-- probe history) so the inner loop doesn't re-run cheap probes.
runInnerLoopFrom
    :: InnerLoopConfig -> Playbook -> InnerLoopState -> IO (InnerLoopState, Maybe Text)
runInnerLoopFrom cfg pb startState = do
    mKey <- lookupEnv "DEEPSEEK_API_KEY"
    case mKey of
        Nothing  -> pure (startState { ilsStopped = Just "DEEPSEEK_API_KEY not set" }
                        , Just "no api key")
        Just key -> do
            finalState <- foldM (step (T.pack key)) startState [1 .. cfgMaxRounds cfg]
            pure (finalState, ilsStopped finalState)
  where
    step :: Text -> InnerLoopState -> Int -> IO InnerLoopState
    step apiKey st n
        | Just _ <- ilsStopped st = pure st
        | otherwise = do
            let st' = st { ilsRound = n }
            let req = defaultRequest (buildLoopPrompt pb st' cfg)
            reply <- (Right <$> callChat apiKey req)
                       `catch` \(e :: SomeException) -> pure (Left (T.pack (show e)))
            let action = parseFromLLM reply
            executeAction cfg action st'
