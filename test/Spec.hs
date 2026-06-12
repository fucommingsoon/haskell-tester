{-# LANGUAGE OverloadedStrings #-}

-- Validate rule classifier against ground truth from distill_out/task_archetypes.jsonl.
-- Loads matching summaries.jsonl rows, runs classify, compares against expected archetype.
-- Reports per-archetype accuracy (should match the 62% Python baseline).
module Main where

import qualified Data.Aeson as A
import qualified Data.ByteString.Char8 as BS
import qualified Data.ByteString.Lazy as BL
import qualified Data.Map.Strict as Map
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.IO as TIO
import System.Exit (exitFailure, exitSuccess)

import HaskellTester.Classifier.Rule (classify)
import HaskellTester.Types


data Assignment = Assignment { aTaskId :: Text, aArchetype :: Text }

instance A.FromJSON Assignment where
    parseJSON = A.withObject "Assignment" $ \o -> Assignment
        <$> o A..: "task_id"
        <*> o A..: "archetype"


loadJsonl :: A.FromJSON a => FilePath -> IO [a]
loadJsonl path = do
    bs <- BS.readFile path
    let lines' = filter (not . BS.null) (BS.lines bs)
    pure $ fmap parseOrDie lines'
  where
    parseOrDie l = case A.eitherDecodeStrict l of
        Right x -> x
        Left e  -> error ("parse error: " <> e)


main :: IO ()
main = do
    summaries    <- loadJsonl "distill_out/summaries.jsonl"     :: IO [TaskSummary]
    assignments  <- loadJsonl "distill_out/task_archetypes.jsonl" :: IO [Assignment]

    let truth = Map.fromList [(aTaskId a, aArchetype a) | a <- assignments]

    let results = [ (tsTaskId s, archetypeName (crArchetype (classify s)),
                     Map.lookup (tsTaskId s) truth)
                  | s <- summaries
                  ]

    let withTruth = [(pred, tru) | (_, pred, Just tru) <- results]
        correct   = length [() | (p, t) <- withTruth, p == t]
        total     = length withTruth
        accuracy  = fromIntegral correct / fromIntegral total :: Double

    putStrLn ("Total tasks evaluated: " <> show total)
    putStrLn ("Correct:               " <> show correct)
    putStrLn ("Accuracy:              " <> show (round (accuracy * 1000) `div` 10 :: Int) <> "%")

    -- Per-archetype breakdown
    putStrLn ""
    putStrLn "Per-archetype accuracy (truth -> hit rate):"
    let byArch = Map.fromListWith (+) [(tru, 1 :: Int) | (_, tru) <- withTruth]
    let hitsByArch = Map.fromListWith (+) [(tru, 1 :: Int) | (p, tru) <- withTruth, p == tru]
    flip mapM_ (Map.toAscList byArch) $ \(arch, n) -> do
        let hits = Map.findWithDefault 0 arch hitsByArch
        let pct  = round (fromIntegral hits / fromIntegral n * 1000 :: Double) `div` 10 :: Int
        putStrLn ("  " <> T.unpack arch <> ":  " <> show hits <> "/" <> show n <> " = " <> show pct <> "%")

    -- The Python baseline is 61.8% — anything materially below means a port bug.
    if accuracy >= 0.55
        then exitSuccess
        else putStrLn "FAIL: accuracy below 55% threshold (Python baseline is ~62%)" >> exitFailure
