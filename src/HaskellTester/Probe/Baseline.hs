{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE DerivingStrategies #-}

-- Deterministic baseline probes run BEFORE classification.
-- Goal: give the runtime classifier the same shape of signal that the dev-time
-- classifier sees (binary format, error grammar, subcommand presence, stdin
-- support, etc.) so it stops defaulting to CliSurfaceAndExitCode.
--
-- These probes are also injected into the inner loop's probe history so the
-- LLM-driven exploration phase doesn't re-run them.
module HaskellTester.Probe.Baseline
    ( BaselineResult (..)
    , BaselineSignals (..)
    , runBaseline
    , renderSignals
    ) where

import Data.Text (Text)
import qualified Data.Text as T
import GHC.Generics (Generic)

import HaskellTester.Probe.Shell


data BaselineSignals = BaselineSignals
    { bsBinaryFormat       :: Text     -- "ELF 64-bit" / "Mach-O" / "Bash script" / ...
    , bsHelpExits0         :: Bool     -- --help rc == 0
    , bsHelpHasUsage       :: Bool     -- --help output contains 'Usage' / 'USAGE' / 'usage'
    , bsHelpListsFlags     :: Bool     -- --help output contains lines starting with '-'
    , bsHasSubcommands     :: Bool     -- --help mentions 'Commands:' / 'SUBCOMMANDS' / etc
    , bsVersionExits0      :: Bool     -- --version rc == 0
    , bsAcceptsStdin       :: Bool     -- empty stdin probe didn't hang/crash + binary kept running
    , bsExitOnInvalidFlag  :: Int      -- exit code for --xyzzy-invalid
    , bsErrorMentionsHelp  :: Bool     -- stderr on invalid flag mentions 'help' or '--help'
    , bsNoArgsBehavior     :: Text     -- "shows-help" / "errors" / "reads-stdin" / "unknown"
    }
    deriving stock (Show, Generic)


data BaselineResult = BaselineResult
    { brProbes  :: [(Text, Text)]      -- (cmd, output) for injection into inner loop kbProbeHistory
    , brSignals :: BaselineSignals
    , brBinary  :: FilePath            -- the binary actually probed
    }
    deriving stock (Show)


-- | Run all baseline probes against the target binary.
runBaseline :: FilePath -> IO BaselineResult
runBaseline bin = do
    fileMagic <- readFileMagic bin
    helpR     <- runHelp bin
    versionR  <- runVersion bin
    noArgsR   <- runNoArgs bin
    invalidR  <- runInvalidFlag bin
    emptyR    <- runProbeWithStdin "" bin []

    let signals = BaselineSignals
            { bsBinaryFormat       = T.take 120 fileMagic
            , bsHelpExits0         = prExitCode helpR == 0
            , bsHelpHasUsage       = anyOf ["usage:", "USAGE:", "Usage:"] (prStdout helpR <> prStderr helpR)
            , bsHelpListsFlags     = countLinesStartingWith "-" (prStdout helpR) >= 2
            , bsHasSubcommands     = anyOf
                ["Commands:", "Subcommands:", "Available Commands:", "SUBCOMMANDS"]
                (prStdout helpR <> prStderr helpR)
            , bsVersionExits0      = prExitCode versionR == 0
            , bsAcceptsStdin       = prExitCode emptyR /= 127  -- 127 = command not found / startup fail
            , bsExitOnInvalidFlag  = prExitCode invalidR
            , bsErrorMentionsHelp  = anyOf ["--help", "-h", "help"] (prStderr invalidR)
            , bsNoArgsBehavior     = classifyNoArgs noArgsR
            }

    -- Probe history entries the inner loop will consume.
    let history =
            [ ("file " <> T.pack bin, fileMagic)
            , (prCmd helpR    <> if T.null (prStdout helpR) then " [stderr]" else "",
               prStdout helpR <> "\n[stderr] " <> prStderr helpR)
            , (prCmd versionR, prStdout versionR <> "\n[stderr] " <> prStderr versionR)
            , (prCmd noArgsR,  prStdout noArgsR  <> "\n[stderr] " <> prStderr noArgsR)
            , (prCmd invalidR, prStdout invalidR <> "\n[stderr] " <> prStderr invalidR)
            , (T.pack bin <> " <empty stdin>",
               prStdout emptyR <> "\n[stderr] " <> prStderr emptyR)
            ]

    pure BaselineResult { brProbes = history, brSignals = signals, brBinary = bin }
  where
    anyOf needles haystack = any (`T.isInfixOf` haystack) needles

    countLinesStartingWith prefix t =
        length [ () | l <- T.lines t, prefix `T.isPrefixOf` T.stripStart l ]

    classifyNoArgs r
        | prExitCode r == 0 && (anyOf ["usage:", "Usage:", "USAGE:"] (prStdout r) || not (T.null (prStdout r)))
            = "shows-help"
        | prExitCode r /= 0 && anyOf ["usage:", "Usage:", "USAGE:"] (prStderr r)
            = "errors-with-usage"
        | prExitCode r /= 0
            = "errors"
        | otherwise
            = "unknown"


-- | Render signals as a compact text block for the LLM classifier prompt.
renderSignals :: BaselineSignals -> Text
renderSignals s = T.unlines
    [ "binary_format:       " <> bsBinaryFormat s
    , "help_exits_0:        " <> tshow (bsHelpExits0 s)
    , "help_has_usage:      " <> tshow (bsHelpHasUsage s)
    , "help_lists_flags:    " <> tshow (bsHelpListsFlags s)
    , "has_subcommands:     " <> tshow (bsHasSubcommands s)
    , "version_exits_0:     " <> tshow (bsVersionExits0 s)
    , "accepts_stdin:       " <> tshow (bsAcceptsStdin s)
    , "exit_on_invalid_flag:" <> tshow (bsExitOnInvalidFlag s)
    , "error_mentions_help: " <> tshow (bsErrorMentionsHelp s)
    , "no_args_behavior:    " <> bsNoArgsBehavior s
    ]
  where
    tshow x = T.pack (show x)
