{-# LANGUAGE OverloadedStrings #-}

-- Build a TaskSummary at runtime from probe results.
--
-- NOTE: at runtime we only have the target binary + SPEC.md, NOT a grader test suite.
-- We can't compute real assertion_distribution. Instead we approximate the summary
-- based on what we can observe (binary type, --help shape, README keywords) and let
-- the classifier work with sparse data. Confidence will often fall through to LLM.
module HaskellTester.Summary
    ( buildRuntimeSummary
    , parseFromJsonFile  -- for dev/testing with existing summaries.jsonl rows
    ) where

import Data.Aeson (eitherDecodeFileStrict)
import qualified Data.ByteString.Lazy as BL
import Data.Map.Strict (Map)
import qualified Data.Map.Strict as Map
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.IO as TIO
import System.Directory (doesFileExist)
import System.FilePath ((</>))

import HaskellTester.Probe.Shell
import HaskellTester.Types


-- Build a sparse TaskSummary from runtime observations of the target.
-- Many fields will be 0 or empty (we don't have the grader's test suite to derive them).
buildRuntimeSummary :: FilePath -> IO TaskSummary
buildRuntimeSummary taskDir = do
    -- Look for SPEC.md or README.md to get task identity + hints.
    spec <- readSpec taskDir
    -- Find the binary (convention: <taskDir>/executable).
    let binary = taskDir </> "executable"
    binExists <- doesFileExist binary
    helpResult <- if binExists then runHelp binary else pure emptyProbe
    versionResult <- if binExists then runVersion binary else pure emptyProbe
    noArgsResult <- if binExists then runNoArgs binary else pure emptyProbe

    pure TaskSummary
        { tsTaskId = identifyTask taskDir spec
        , tsNBranches = 0          -- unknown at runtime
        , tsNTests = 0              -- unknown
        , tsPopenCalls = 0          -- unknown; rule classifier may default to CLI
        , tsAssertionDistribution = Map.empty  -- can't compute without grader
        , tsInvocationPatterns = Map.empty
        , tsExpectedValueSamples = scrapeExpectedFromProbe helpResult versionResult noArgsResult
        , tsDocstringSamples = [spec]
        , tsTestFiles = []
        }
  where
    emptyProbe = ProbeResult "" "" "" (-1)


readSpec :: FilePath -> IO Text
readSpec taskDir = do
    -- Try a battery of common README/SPEC variants, case-insensitive on stem.
    let candidates =
            [ taskDir </> "SPEC.md"
            , taskDir </> "README.md"
            , taskDir </> "README.mkd"
            , taskDir </> "README.markdown"
            , taskDir </> "README.rst"
            , taskDir </> "README.txt"
            , taskDir </> "README.adoc"
            , taskDir </> "README.org"
            , taskDir </> "README"
            , taskDir </> "readme.md"
            , taskDir </> "readme.txt"
            , taskDir </> "Readme.md"
            ]
    let tryRead [] = pure ""
        tryRead (p : ps) = do
            ok <- doesFileExist p
            if ok then TIO.readFile p else tryRead ps
    tryRead candidates


identifyTask :: FilePath -> Text -> Text
identifyTask taskDir spec =
    let dirName = T.pack (last (splitOn '/' taskDir))
        -- Try to extract a project URL from spec if mentioned
    in dirName
  where
    splitOn c = words . map (\ch -> if ch == c then ' ' else ch)


-- Pull keyword-like tokens from probe stdouts to seed expected_value_samples.
-- Helps the LLM classifier even when assertion_distribution is empty.
scrapeExpectedFromProbe :: ProbeResult -> ProbeResult -> ProbeResult -> [Text]
scrapeExpectedFromProbe h v _ =
    take 15 (T.words (prStdout h) <> T.words (prStdout v))


-- For dev/testing: parse a TaskSummary record from a summaries.jsonl row.
parseFromJsonFile :: FilePath -> IO (Either String TaskSummary)
parseFromJsonFile = eitherDecodeFileStrict
