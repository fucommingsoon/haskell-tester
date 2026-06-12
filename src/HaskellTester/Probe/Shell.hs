{-# LANGUAGE OverloadedStrings #-}

-- Runtime probe layer: run cheap shell commands against the target binary.
-- This is the "probe" phase of the inner loop — extract observable facts.
module HaskellTester.Probe.Shell
    ( ProbeResult (..)
    , runProbe
    , runProbeWithStdin
    , runHelp
    , runVersion
    , runNoArgs
    , runInvalidFlag
    , readFileMagic
    , runNm
    ) where

import Data.Text (Text)
import qualified Data.Text as T
import System.Exit (ExitCode (..))
import System.Process (readProcessWithExitCode)


data ProbeResult = ProbeResult
    { prCmd      :: Text       -- the command that was run
    , prStdout   :: Text
    , prStderr   :: Text
    , prExitCode :: Int
    }
    deriving (Show)


-- Run a probe with a 5-second timeout and capture all streams.
runProbe :: FilePath -> [String] -> IO ProbeResult
runProbe = runProbeWithStdin ""


-- Run a probe with optional stdin (used for stdin-driven binaries: cat | bin).
runProbeWithStdin :: String -> FilePath -> [String] -> IO ProbeResult
runProbeWithStdin stdin' cmd args = do
    (ec, out, err) <- readProcessWithExitCode cmd args stdin'
    pure ProbeResult
        { prCmd      = T.pack (unwords (cmd : args))
        , prStdout   = T.pack out
        , prStderr   = T.pack err
        , prExitCode = case ec of
            ExitSuccess   -> 0
            ExitFailure n -> n
        }


-- Run the target with --help.
runHelp :: FilePath -> IO ProbeResult
runHelp bin = runProbe bin ["--help"]


-- Run the target with --version (some tools use -V, fallback to that on nonzero).
runVersion :: FilePath -> IO ProbeResult
runVersion bin = do
    r <- runProbe bin ["--version"]
    if prExitCode r /= 0
        then runProbe bin ["-V"]
        else pure r


-- Run the target with no arguments. Many CLIs print usage to stderr and exit nonzero.
runNoArgs :: FilePath -> IO ProbeResult
runNoArgs bin = runProbe bin []


-- Run the target with an obviously invalid flag, to probe error grammar.
runInvalidFlag :: FilePath -> IO ProbeResult
runInvalidFlag bin = runProbe bin ["--xyzzy-definitely-not-a-real-flag"]


-- `file <bin>` magic — what kind of binary is this (ELF, Mach-O, script).
readFileMagic :: FilePath -> IO Text
readFileMagic bin = do
    (_, out, _) <- readProcessWithExitCode "file" [bin] ""
    pure (T.strip (T.pack out))


-- `nm --defined-only <bin> | head` — first 20 defined symbols. Useful for SubcommandDispatch probing.
runNm :: FilePath -> IO Text
runNm bin = do
    (_, out, _) <- readProcessWithExitCode "nm" ["--defined-only", bin] ""
    pure (T.unlines (take 20 (T.lines (T.pack out))))
