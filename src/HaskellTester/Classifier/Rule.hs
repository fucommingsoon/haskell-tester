{-# LANGUAGE OverloadedStrings #-}

-- Port of scripts/classifier.py rule logic.
-- Same thresholds; same decision order; same outputs as the Python prototype.
module HaskellTester.Classifier.Rule (classify) where

import Data.Map.Strict (Map)
import qualified Data.Map.Strict as Map
import Data.Text (Text)
import qualified Data.Text as T

import HaskellTester.Types


-- Look up assertion distribution share, default 0.
dist :: TaskSummary -> Text -> Double
dist s k = Map.findWithDefault 0 k (tsAssertionDistribution s)


hasGoldenInDocstrings :: TaskSummary -> Bool
hasGoldenInDocstrings = any goldenLike . tsDocstringSamples
  where
    goldenLike d = "golden" `T.isInfixOf` T.toLower d
                || "Golden files:" `T.isInfixOf` d


hasLintInFiles :: TaskSummary -> Bool
hasLintInFiles s = any hit (tsTestFiles s)
  where
    hit f = any (`T.isInfixOf` T.toLower f) ["lint", "checker", "diagnost"]


hasTuiInFiles :: TaskSummary -> Bool
hasTuiInFiles s = any hit (tsTestFiles s)
  where
    hit f = let l = T.toLower f
            in any (`T.isInfixOf` l) ["test_tui_", "test_interactive", "test_screen"]


hasScreenGolden :: TaskSummary -> Bool
hasScreenGolden s = any hit (tsDocstringSamples s)
  where
    hit d = any (`T.isInfixOf` d) ["screen", "snapshot", ".golden -- ", "title_", "state_"]


-- ctags-style: massive test count, repeated template docstring.
isMassiveFixture :: TaskSummary -> Bool
isMassiveFixture s =
    tsNTests s >= 1500
    && length docs >= 4
    && length (uniqueHeads docs) <= 2
  where
    docs = tsDocstringSamples s
    uniqueHeads = uniq . map (T.take 80)
    uniq xs = foldr (\x acc -> if x `elem` acc then acc else x : acc) [] xs


classify :: TaskSummary -> ClassifyResult
classify s
    -- Rule 1: massive fixture suite.
    | isMassiveFixture s =
        ClassifyResult MassiveFixtureSuite 0.95
            [T.pack $ "n_tests=" <> show (tsNTests s) <> " + repeated docstring template"]
            RuleFastPath

    -- Rule 2: orchestration-driven (popen-using watcher).
    | tsPopenCalls s >= 5 =
        ClassifyResult OrchestrationDrivenWatcher 0.90
            [T.pack $ "popen_calls=" <> show (tsPopenCalls s) <> " (>= 5 threshold)"]
            RuleFastPath

    -- Rule 3: numeric tolerance (inequality bounds dominate).
    | boundTotal >= 0.20 =
        ClassifyResult NumericTolerance 0.85
            [fmtNum "other.gt+ge+lt+le" boundTotal <> " >= 0.20"]
            RuleFastPath

    -- Rule 4: linter (test files + diagnostic-style assertions).
    | hasLintInFiles s && (othEq >= 0.15 || othIn >= 0.15) =
        ClassifyResult LinterDiagnostic 0.75
            ["test files mention lint/diagnostic + other.eq/contains high"]
            RuleFastPath

    -- Rule 5: TUI screen snapshot.
    | rcEq < 0.15
      && otherTotal >= 0.45
      && (hasTuiInFiles s || hasScreenGolden s) =
        ClassifyResult TuiScreenSnapshot 0.75
            [fmtNum "rc.eq" rcEq <> " low + " <> fmtNum "other.*" otherTotal <> " high + TUI/screen signal"]
            RuleFastPath

    -- Rule 6: ByteExactGolden (strong: stdout.eq >= 0.15).
    | soEq >= 0.15 =
        ClassifyResult ByteExactGolden (if goldenDoc then 0.85 else 0.75)
            [fmtNum "stdout.eq" soEq <> " >= 0.15"]
            RuleFastPath

    -- Rule 6b: ByteExactGolden via other.eq + golden docstrings.
    | othEq >= 0.20 && goldenDoc =
        ClassifyResult ByteExactGolden 0.75
            [fmtNum "other.eq" othEq <> " + golden in docstrings"]
            RuleFastPath

    -- Rule 7: FilesystemSideEffect (other.truthy/contains dominate, no TUI signal).
    | othTr + othIn >= 0.30 && soEq < 0.10 && not (hasTuiInFiles s) =
        ClassifyResult FilesystemSideEffect 0.70
            [fmtNum "other.truthy+contains" (othTr + othIn) <> " >= 0.30, no TUI signal"]
            RuleFastPath

    -- Rule 8: ByteExactGolden weak (moderate stdout.eq + golden docstrings).
    | soEq >= 0.08 && goldenDoc =
        ClassifyResult ByteExactGolden 0.65
            [fmtNum "stdout.eq" soEq <> " + golden in docstrings"]
            RuleFastPath

    -- Rule 9: default CLI surface (most common archetype).
    | rcEq >= 0.15 =
        let conf = if (soIn + seIn) >= 0.10 then 0.75 else 0.60
        in ClassifyResult CliSurfaceAndExitCode conf
               [fmtNum "returncode.eq" rcEq <> " >= 0.15 (default CLI)"]
               RuleFastPath

    -- Rule 10: last resort.
    | otherwise =
        ClassifyResult CliSurfaceAndExitCode 0.40
            ["no strong signal, defaulting to CLI"]
            RuleFastPath
  where
    rcEq       = dist s "returncode.eq"
    soEq       = dist s "stdout.eq"
    soIn       = dist s "stdout.contains"
    seIn       = dist s "stderr.contains"
    othEq      = dist s "other.eq"
    othIn      = dist s "other.contains"
    othTr      = dist s "other.truthy"
    othGt      = dist s "other.gt"
    othGe      = dist s "other.ge"
    othLt      = dist s "other.lt"
    othLe      = dist s "other.le"
    boundTotal = othGt + othGe + othLt + othLe
    otherTotal = othEq + othIn + othTr
    goldenDoc  = hasGoldenInDocstrings s

    fmtNum label v = T.pack $ label <> "=" <> printNum v
    printNum v = let s' = show v in take (min 5 (length s')) s'
