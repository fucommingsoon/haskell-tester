{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE DerivingStrategies #-}

-- Batch validation runner: replaces scripts/batch_pb_density.py.
--
-- For each (system_binary, pb_task_id) pair:
--   1. Extract README from cached HF tarball via shell `tar`
--   2. Symlink the system binary as `executable`
--   3. Spawn `htester agent <dir>` subprocess
--   4. Parse agent stdout for classification + counts
--   5. Run FactExtract on README + belief.md to compute net_new
--   6. Append row
--
-- At end, print summary table.
module HaskellTester.Evaluation.BatchRunner
    ( BatchRow (..)
    , runBatch
    , runBatchVariance
    ) where

import Control.Monad (forM, forM_)
import Data.List (sortBy)
import Data.Map.Strict (Map)
import qualified Data.Map.Strict as Map
import Data.Maybe (fromMaybe)
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.IO as TIO
import GHC.Generics (Generic)
import System.Directory (doesFileExist, createDirectoryIfMissing, removeDirectoryRecursive, listDirectory)
import System.Exit (ExitCode (..))
import System.FilePath ((</>), takeFileName)
import System.IO (hFlush, stdout)
import System.Process (readProcessWithExitCode)
import Text.Printf (printf)
import Text.Read (readMaybe)

import HaskellTester.Evaluation.FactExtract


-- A list of (binary_path, pb_task_id, expected_archetype_for_display) entries.
defaultBatch :: [(FilePath, Text, Text)]
defaultBatch =
    [ ("/usr/bin/jq",            "jqlang__jq.b33a763",          "ByteExactGolden")
    , ("/opt/homebrew/bin/rg",   "burntsushi__ripgrep.3b7fd44", "ByteExactGolden")
    , ("/opt/homebrew/bin/yq",   "mikefarah__yq.602586d",       "ByteExactGolden")
    , ("/opt/homebrew/bin/gron", "tomnomnom__gron.88a6234",     "ByteExactGolden")
    , ("/opt/homebrew/bin/fd",   "sharkdp__fd.40d8eb3",         "CliSurfaceAndExitCode")
    ]


hfRoot :: FilePath
hfRoot = "/Users/kangxin/.cache/huggingface/hub/datasets--programbench--ProgramBench-Tests/"
      <> "snapshots/de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5"


htesterBin :: FilePath
htesterBin = "dist-newstyle/build/aarch64-osx/ghc-9.6.7/haskell-tester-0.1.0.0/x/htester/build/htester/htester"


data BatchRow = BatchRow
    { brTask       :: Text
    , brTruth      :: Text
    , brPredicted  :: Text
    , brRounds     :: Int
    , brProbes     :: Int
    , brReadmeN    :: Int
    , brBeliefN    :: Int
    , brOverlap    :: Int
    , brNetNew     :: Int
    }
    deriving stock (Show, Generic)


-- Run the full batch ONCE: agent on each task, then density.
runBatch :: IO [BatchRow]
runBatch = do
    fmap (filter (\r -> brBeliefN r > 0)) $ forM defaultBatch $ \(bin, tid, truth) -> do
        let short = T.takeWhileEnd (/= '_') (T.takeWhile (/= '.') tid)
        let workDir = "/tmp/pb_batch_" <> T.unpack short
        putStrLn $ "=== " <> T.unpack short <> " (bin=" <> bin <> ") ==="

        ok <- setupTestDir tid bin workDir
        if not ok
            then do
                putStrLn "  SKIP: setup failed"
                pure (emptyRow short truth)
            else do
                (predicted, rounds, probes, beliefOk) <- runAgent workDir
                if not beliefOk
                    then do
                        putStrLn "  SKIP: agent failed to produce belief"
                        pure (emptyRow short truth)
                    else do
                        report <- buildReport (workDir </> "README.md") (workDir </> "belief.md")
                        let row = BatchRow
                                { brTask      = short
                                , brTruth     = truth
                                , brPredicted = predicted
                                , brRounds    = rounds
                                , brProbes    = probes
                                , brReadmeN   = drReadmeFacts report
                                , brBeliefN   = drBeliefFacts report
                                , brOverlap   = drOverlap report
                                , brNetNew    = drNetNew report
                                }
                        printf "  archetype=%s  rounds=%d  README=%d  belief=%d  NEW=%d\n"
                            (T.unpack predicted) rounds
                            (drReadmeFacts report) (drBeliefFacts report) (drNetNew report)
                        hFlush stdout
                        pure row


-- Run the batch N times to measure variance across repeated runs.
runBatchVariance :: Int -> IO ()
runBatchVariance n = do
    putStrLn $ "Running batch " <> show n <> " times for variance check..."
    runs <- forM [1 .. n] $ \i -> do
        putStrLn $ "\n==== RUN " <> show i <> "/" <> show n <> " ===="
        runBatch
    putStrLn "\n\n=== VARIANCE SUMMARY ==="
    let byTask = Map.fromListWith (++) [(brTask r, [brNetNew r]) | rs <- runs, r <- rs]
    printf "%-12s %-8s %-8s %-8s %-8s %-8s\n"
        ("task" :: String) ("runs" :: String) ("min" :: String)
        ("max" :: String) ("mean" :: String) ("spread%" :: String)
    putStrLn (replicate 60 '-')
    let entries = sortBy (\a b -> compare (fst a) (fst b)) (Map.toList byTask)
    forM_ entries $ \(task, values) -> do
        let lo = minimum values
            hi = maximum values
            mean = fromIntegral (sum values) / fromIntegral (length values) :: Double
            spread = if hi == 0 then 0
                     else 100 * fromIntegral (hi - lo) / fromIntegral hi
        printf "%-12s %-8d %-8d %-8d %-8.1f %-8.0f\n"
            (T.unpack task) (length values) lo hi mean (spread :: Double)


setupTestDir :: Text -> FilePath -> FilePath -> IO Bool
setupTestDir taskId bin workDir = do
    -- Wipe + recreate.
    _ <- readProcessWithExitCode "rm" ["-rf", workDir] ""
    createDirectoryIfMissing True workDir
    -- Find first tarball
    let taskDir = hfRoot </> T.unpack taskId </> "tests"
    tarballs <- listDirectory taskDir
    case filter (".tar.gz" `T.isSuffixOf`) (map T.pack tarballs) of
        [] -> pure False
        (tarFile : _) -> do
            -- Extract just the readme-like files (case-insensitive prefix)
            let tarPath = taskDir </> T.unpack tarFile
            (_, listing, _) <- readProcessWithExitCode "tar" ["-tzf", tarPath] ""
            let readmes = filter isReadme (lines listing)
            let chosen = pickBestReadme readmes
            case chosen of
                Nothing -> pure False
                Just rdm -> do
                    (ec, _, _) <- readProcessWithExitCode "tar"
                                  ["-xzf", tarPath, "-C", workDir, rdm] ""
                    case ec of
                        ExitSuccess -> do
                            -- Hoist to top-level README.md
                            let extracted = workDir </> rdm
                            let target    = workDir </> "README.md"
                            exists <- doesFileExist extracted
                            if exists && extracted /= target
                                then readProcessWithExitCode "mv" [extracted, target] "" >> pure ()
                                else pure ()
                            -- Symlink binary
                            readProcessWithExitCode "ln" ["-sf", bin, workDir </> "executable"] ""
                                >> pure True
                        _ -> pure False
  where
    catchExtract action _handler = action  -- placeholder; safe enough for dev tooling


isReadme :: String -> Bool
isReadme path =
    let stem = takeFileName path
        low  = map toLower' stem
    in "readme" `prefixOf` low && not (any (`endsWith` low) skipExts)
  where
    skipExts = [".png", ".jpg", ".gif", ".jsonl", ".golden", ".js"]
    toLower' c | c >= 'A' && c <= 'Z' = toEnum (fromEnum c + 32)
               | otherwise            = c
    prefixOf p s = take (length p) s == p
    endsWith suf s = drop (length s - length suf) s == suf


pickBestReadme :: [String] -> Maybe String
pickBestReadme files =
    let prio name = case findExt name of
            Just ".md"       -> 0
            Just ".mkd"      -> 1
            Just ".markdown" -> 2
            Just ".rst"      -> 3
            Just ".adoc"     -> 4
            Just ".org"      -> 5
            Just ".txt"      -> 6
            Just _           -> 7
            Nothing          -> 8
        ranked = sortBy (\a b -> compare (prio a) (prio b)) files
    in case ranked of
        (x:_) -> Just x
        []    -> Nothing
  where
    findExt s = case dropWhile (/= '.') (reverse s) of
        ""  -> Nothing
        rev -> Just (reverse rev)


runAgent :: FilePath -> IO (Text, Int, Int, Bool)
runAgent workDir = do
    (_, out, _) <- readProcessWithExitCode htesterBin ["agent", workDir] ""
    let archetype = extractField "Archetype:" out
    let rounds    = fromMaybe 0 (readMaybe =<< Just (extractField "Rounds run:" out))
    let probes    = fromMaybe 0 (readMaybe =<< Just (extractField "Probes executed:" out))
    beliefOk <- doesFileExist (workDir </> "belief.md")
    pure (T.pack archetype, rounds, probes, beliefOk)
  where
    extractField key s =
        case dropWhile (not . prefixed key) (lines s) of
            (line : _) -> takeWhile (/= ' ') (dropWhile (== ' ') (drop (length key) line))
            []         -> ""
    prefixed key l = take (length key) l == key


emptyRow :: Text -> Text -> BatchRow
emptyRow t tr = BatchRow t tr "" 0 0 0 0 0 0
