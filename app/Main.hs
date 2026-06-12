{-# LANGUAGE OverloadedStrings #-}

module Main where

import Control.Exception (catch, SomeException)
import Control.Monad (foldM)
import qualified Data.Aeson as A
import qualified Data.Aeson.KeyMap as KM
import qualified Data.ByteString.Char8 as BSC
import qualified Data.ByteString.Lazy.Char8 as BL
import qualified Data.Map.Strict as Map
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.IO as TIO
import System.Environment (getArgs)
import System.Exit (exitFailure)
import System.IO (hFlush, stdout)
import Text.Printf (printf)

import qualified HaskellTester.Classifier.Hybrid as Hybrid
import qualified HaskellTester.Classifier.LLM as LLM
import qualified HaskellTester.Classifier.Rule as Rule
import qualified HaskellTester.Probe.Baseline as Baseline
import HaskellTester.EmbeddedData (embeddedTaxonomy)
import qualified HaskellTester.Evaluation.BatchRunner as Batch
import qualified HaskellTester.InnerLoop as InnerLoop
import HaskellTester.Playbook
import HaskellTester.Summary
import HaskellTester.Types


usage :: IO ()
usage = do
    putStrLn "Usage:"
    putStrLn "  htester classify <summary.json>          # rule-only classify"
    putStrLn "  htester classify-hybrid <summary.json>   # rule + LLM fallback (needs DEEPSEEK_API_KEY)"
    putStrLn "  htester probe <task_dir>                 # build runtime summary, classify, load playbook"
    putStrLn "  htester agent <task_dir>                 # full agent: probe -> classify -> playbook -> inner loop"
    putStrLn "  htester taxonomy                         # dump archetype taxonomy"
    putStrLn "  htester validate-hybrid [limit]          # run hybrid classifier on full ground truth, report accuracy"
    putStrLn "  htester validate-batch [runs]            # run agent on system binaries + measure net_new (variance check)"
    exitFailure


main :: IO ()
main = do
    args <- getArgs
    case args of
        ["classify", path]            -> doClassify Rule.classify path
        ["classify-hybrid", path]     -> doClassifyIO Hybrid.classify path
        ["probe", taskDir]            -> doProbe taskDir
        ["agent", taskDir]            -> doAgent taskDir Nothing
        ["agent", "--archetype", a, taskDir] -> doAgent taskDir (archetypeFromName (T.pack a))
        ["taxonomy"]                  -> doTaxonomy
        ["validate-hybrid"]           -> doValidateHybrid 0
        ["validate-hybrid", limitStr] -> doValidateHybrid (read limitStr)
        ["validate-batch"]            -> Batch.runBatchVariance 1
        ["validate-batch", runsStr]   -> Batch.runBatchVariance (read runsStr)
        _                             -> usage


printResult :: TaskSummary -> ClassifyResult -> IO ()
printResult summary result = do
    putStrLn ("Task:       " <> T.unpack (tsTaskId summary))
    putStrLn ("Archetype:  " <> T.unpack (archetypeName (crArchetype result)))
    putStrLn ("Confidence: " <> show (crConfidence result))
    putStrLn ("Reasons:    " <> T.unpack (T.intercalate ", " (crReasons result)))
    putStrLn ("Source:     " <> show (crSource result))


doClassify :: (TaskSummary -> ClassifyResult) -> FilePath -> IO ()
doClassify cls path = do
    res <- parseFromJsonFile path
    case res of
        Left err -> putStrLn ("Failed to parse summary: " <> err) >> exitFailure
        Right summary -> printResult summary (cls summary)


doClassifyIO :: (TaskSummary -> IO ClassifyResult) -> FilePath -> IO ()
doClassifyIO cls path = do
    res <- parseFromJsonFile path
    case res of
        Left err -> putStrLn ("Failed to parse summary: " <> err) >> exitFailure
        Right summary -> cls summary >>= printResult summary


doAgent :: FilePath -> Maybe Archetype -> IO ()
doAgent taskDir overrideArch = do
    putStrLn ("=== Phase 1: read README + locate binary in " <> taskDir <> " ===")
    summary <- buildRuntimeSummary taskDir

    -- Locate the binary inside the task dir.
    let binPath = taskDir <> "/executable"
    putStrLn ("Binary: " <> binPath)

    putStrLn ""
    putStrLn "=== Phase 2: baseline probes (6 deterministic) ==="
    baseline <- Baseline.runBaseline binPath
    let bsigs = Baseline.brSignals baseline
    putStrLn ("  binary_format:      " <> T.unpack (Baseline.bsBinaryFormat bsigs))
    putStrLn ("  help_exits_0:       " <> show (Baseline.bsHelpExits0 bsigs))
    putStrLn ("  has_subcommands:    " <> show (Baseline.bsHasSubcommands bsigs))
    putStrLn ("  accepts_stdin:      " <> show (Baseline.bsAcceptsStdin bsigs))
    putStrLn ("  no_args_behavior:   " <> T.unpack (Baseline.bsNoArgsBehavior bsigs))
    putStrLn ("  invalid_flag_rc:    " <> show (Baseline.bsExitOnInvalidFlag bsigs))

    putStrLn ""
    result <- case overrideArch of
        Just a -> do
            putStrLn ("=== Phase 3: archetype FORCED via --archetype to " <> T.unpack (archetypeName a) <> " ===")
            pure ClassifyResult { crArchetype = a, crConfidence = 1.0
                                , crReasons = ["forced via --archetype CLI"]
                                , crSource = RuleFastPath }
        Nothing -> do
            putStrLn "=== Phase 3: classify (runtime: README + baseline -> LLM) ==="
            -- README content is held in docstring_samples by buildRuntimeSummary.
            let readme = T.intercalate "\n" (tsDocstringSamples summary)
            LLM.classifyRuntime readme baseline
    printResult summary result

    putStrLn ""
    putStrLn "=== Phase 3: load playbook for archetype (embedded) ==="
    pb <- loadEmbeddedPlaybook (crArchetype result)
    putStrLn ("Playbook loaded: " <> show (length (pbSections pb)) <> " sections")

    putStrLn ""
    putStrLn "=== Phase 4: inner loop (probe -> hypothesize -> verify) ==="
    let cfg = InnerLoop.defaultConfig binPath
    -- Seed inner loop with baseline probe history so LLM doesn't redo --help/--version etc.
    let seededState = InnerLoop.initialState
            { InnerLoop.ilsKB = InnerLoop.emptyKB
                { InnerLoop.kbProbeHistory = reverse (Baseline.brProbes baseline) }
            }
    putStrLn ("(seeded " <> show (length (Baseline.brProbes baseline)) <> " baseline probes into state)")
    (finalState, stopReason) <- InnerLoop.runInnerLoopFrom cfg pb seededState
    putStrLn ("Rounds run: " <> show (InnerLoop.ilsRound finalState))
    case stopReason of
        Just r  -> putStrLn ("Stop reason: " <> T.unpack r)
        Nothing -> putStrLn "Stop reason: max rounds hit (no LLM stop)"

    let history = reverse (InnerLoop.kbProbeHistory (InnerLoop.ilsKB finalState))
    let kb = InnerLoop.ilsKB finalState

    -- Write structured belief.md to task_dir for downstream consumption.
    let beliefPath = taskDir <> "/belief.md"
    writeBeliefMarkdown beliefPath taskDir summary result pb history kb stopReason
    putStrLn ""
    putStrLn ("=== Belief written to " <> beliefPath <> " ===")
    putStrLn ("Probes executed: " <> show (length history))
    putStrLn ("Verified hypotheses: " <> show (length (InnerLoop.kbVerified kb)))
    putStrLn ("Grounded facts: " <> show (length (InnerLoop.kbFacts kb)))


writeBeliefMarkdown
    :: FilePath
    -> FilePath
    -> TaskSummary
    -> ClassifyResult
    -> Playbook
    -> [(Text, Text)]
    -> InnerLoop.KnowledgeBase
    -> Maybe Text
    -> IO ()
writeBeliefMarkdown path taskDir summary result pb history kb stopReason = do
    let txt = T.unlines $ concat
            [ [ "# Belief: " <> T.pack taskDir ]
            , [ "" ]
            , [ "Task id: " <> tsTaskId summary ]
            , [ "Archetype: " <> archetypeName (crArchetype result)
                <> " (confidence " <> T.pack (show (crConfidence result)) <> ", "
                <> T.pack (show (crSource result)) <> ")" ]
            , [ "" ]
            , [ "## Classification reason" ]
            , map ("- " <>) (crReasons result)
            , [ "" ]
            , [ "## Stop reason" ]
            , [ maybe "max rounds hit (no LLM stop)" id stopReason ]
            , [ "" ]
            , [ "## Verified hypotheses (verify action)" ]
            , [ "Total: " <> T.pack (show (length (InnerLoop.kbVerified kb))) ]
            , [ "" ]
            , map (\h -> "- " <> InnerLoop.hClaim h <> "  (oracle: " <> InnerLoop.hOracle h <> ")")
                  (InnerLoop.kbVerified kb)
            , [ "" ]
            , [ "## Grounded facts (stop findings)" ]
            , [ "Total: " <> T.pack (show (length (InnerLoop.kbFacts kb))) ]
            , [ "" ]
            , map ("- " <>) (InnerLoop.kbFacts kb)
            , [ "" ]
            , [ "## Probe history" ]
            , [ "Executed: " <> T.pack (show (length history)) <> " commands" ]
            , [ "" ]
            , concat
                [ [ "### round " <> T.pack (show i)
                  , "```"
                  , "$ " <> cmd
                  , T.take 500 out
                  , "```"
                  , ""
                  ]
                | (i, (cmd, out)) <- zip [(1 :: Int) ..] history
                ]
            , [ "## Playbook used (sections)" ]
            , map (\(h, _) -> "- " <> h) (pbSections pb)
            ]
    TIO.writeFile path txt


doProbe :: FilePath -> IO ()
doProbe taskDir = do
    summary <- buildRuntimeSummary taskDir
    let result = Rule.classify summary
    putStrLn ("Task dir:   " <> taskDir)
    printResult summary result
    -- Load matching playbook so agent can use it as LLM system prompt.
    pb <- loadEmbeddedPlaybook (crArchetype result)
    putStrLn ""
    putStrLn ("Playbook loaded: " <> show (length (pbSections pb)) <> " sections")
    putStrLn "First section heading:"
    case pbSections pb of
        ((h, _) : _) -> TIO.putStrLn ("  " <> h)
        []           -> putStrLn "  (no sections found)"


-- Run hybrid classifier on full ground truth, report accuracy.
-- Automatically excludes tasks listed in distill_out/fewshot_task_ids.json (if exists)
-- so the eval isn't contaminated by tasks that were embedded as few-shot examples.
doValidateHybrid :: Int -> IO ()
doValidateHybrid limit = do
    summariesBytes <- BSC.readFile "distill_out/summaries.jsonl"
    truthBytes     <- BSC.readFile "distill_out/task_archetypes.jsonl"

    let summaries  = parseJsonl summariesBytes :: [TaskSummary]
    let truthPairs = parseJsonl truthBytes     :: [TruthRow]
    let truth      = Map.fromList [(trTaskId t, trArchetype t) | t <- truthPairs]

    -- Load few-shot exclusion set if present.
    fewShotIds <- loadFewShotIds
    let cleaned = filter (\s -> tsTaskId s `notElem` fewShotIds) summaries

    case fewShotIds of
        [] -> putStrLn "Note: no few-shot exclusion list found."
        xs -> putStrLn ("Excluding " <> show (length xs) <> " few-shot task ids from eval.")

    let sampled =
            if limit > 0 then take limit cleaned else cleaned
    let total = length sampled

    putStrLn ("Validating " <> show total <> " tasks with hybrid classifier...")
    putStrLn ""

    (correctRule, totalRule, correctLLM, totalLLM, confusion) <- foldM
        (\(cR, tR, cL, tL, cf) (i, s) -> do
            let tid = tsTaskId s
            r <- Hybrid.classify s
            let predicted = archetypeName (crArchetype r)
            let truthLabel = Map.lookup tid truth
            let isRule = crSource r == RuleFastPath
            let isCorrect = maybe False (== predicted) truthLabel
            let mark = if isCorrect then "✓" else "✗"
            let srcTag = if isRule then "rule" else "llm " :: String
            printf "[%3d/%d] %s %s %s  ->  %s%s\n"
                i total (mark :: String) srcTag (take 50 (T.unpack tid)) (T.unpack predicted)
                (case truthLabel of
                    Just t  -> "  (truth=" <> T.unpack t <> ")"
                    Nothing -> "")
            hFlush stdout
            let cf' = case truthLabel of
                    Just tl | not isCorrect ->
                        Map.insertWith (+) (tl, predicted) (1 :: Int) cf
                    _ -> cf
            pure ( if isRule && isCorrect then cR + 1 else cR
                 , if isRule           then tR + 1 else tR
                 , if not isRule && isCorrect then cL + 1 else cL
                 , if not isRule       then tL + 1 else tL
                 , cf' ))
        (0 :: Int, 0 :: Int, 0 :: Int, 0 :: Int, Map.empty)
        (zip [(1 :: Int) ..] sampled)

    let totalCorrect = correctRule + correctLLM
    let totalSeen    = totalRule + totalLLM

    putStrLn ""
    printf "Overall:        %d/%d = %.1f%%\n" totalCorrect totalSeen
        (100 * fromIntegral totalCorrect / fromIntegral totalSeen :: Double)
    printf "  rule path:    %d/%d = %.1f%%\n" correctRule totalRule
        (if totalRule == 0 then 0.0 else 100 * fromIntegral correctRule / fromIntegral totalRule :: Double)
    printf "  LLM fallback: %d/%d = %.1f%%\n" correctLLM totalLLM
        (if totalLLM == 0 then 0.0 else 100 * fromIntegral correctLLM / fromIntegral totalLLM :: Double)
    putStrLn ""
    putStrLn "Top confusion (truth -> predicted):"
    mapM_ (\((tr, pr), n) ->
        printf "  %3d  %s -> %s\n" n (T.unpack tr) (T.unpack pr))
        (take 10 (Map.toList confusion))


loadFewShotIds :: IO [Text]
loadFewShotIds = do
    let path = "distill_out/fewshot_task_ids.json"
    bs <- BL.readFile path
    case A.decode bs :: Maybe [Text] of
        Just xs -> pure xs
        Nothing -> pure []
    `catch` \(_ :: SomeException) -> pure []


data TruthRow = TruthRow { trTaskId :: Text, trArchetype :: Text }
instance A.FromJSON TruthRow where
    parseJSON = A.withObject "TruthRow" $ \o -> TruthRow
        <$> o A..: "task_id"
        <*> o A..: "archetype"


parseJsonl :: A.FromJSON a => BSC.ByteString -> [a]
parseJsonl bs =
    [ x | line <- BSC.lines bs, not (BSC.null line)
        , Just x <- [A.decodeStrict line] ]


doTaxonomy :: IO ()
doTaxonomy = do
    -- Pretty-print top-level archetype names from the embedded taxonomy.
    case A.decodeStrict embeddedTaxonomy :: Maybe A.Object of
        Just obj -> do
            putStrLn "Archetypes in taxonomy (embedded):"
            mapM_ (\k -> putStrLn ("  - " <> show k)) (KM.keys obj)
        Nothing -> putStrLn "Failed to decode embedded taxonomy"
