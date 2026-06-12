{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DerivingStrategies #-}

module HaskellTester.Types where

import Data.Aeson
import Data.Map.Strict (Map)
import qualified Data.Map.Strict as Map
import Data.Text (Text)
import qualified Data.Text as T
import GHC.Generics (Generic)


data Archetype
    = ByteExactGolden
    | CliSurfaceAndExitCode
    | FilesystemSideEffect
    | TuiScreenSnapshot
    | LinterDiagnostic
    | NumericTolerance
    | OrchestrationDrivenWatcher
    | MassiveFixtureSuite
    deriving stock (Eq, Show, Ord, Bounded, Enum, Generic)

archetypeName :: Archetype -> Text
archetypeName = T.pack . show

archetypeFromName :: Text -> Maybe Archetype
archetypeFromName name = lookup (T.unpack name) names
  where
    names = [(show a, a) | a <- [minBound .. maxBound]]


data AssertionTarget = TargetReturncode | TargetStdout | TargetStderr | TargetOther
    deriving stock (Eq, Show, Ord, Generic)

data AssertionOp
    = OpEq | OpNeq | OpContains | OpNotContains
    | OpGt | OpGe | OpLt | OpLe
    | OpTruthy | OpOther
    deriving stock (Eq, Show, Ord, Generic)


data TaskSummary = TaskSummary
    { tsTaskId               :: Text
    , tsNBranches            :: Int
    , tsNTests               :: Int
    , tsPopenCalls           :: Int
    , tsAssertionDistribution :: Map Text Double
    , tsInvocationPatterns   :: Map Text Int
    , tsExpectedValueSamples :: [Text]
    , tsDocstringSamples     :: [Text]
    , tsTestFiles            :: [Text]
    }
    deriving stock (Eq, Show, Generic)


-- JSON instances mirror the format emitted by summarize_features.py
instance FromJSON TaskSummary where
    parseJSON = withObject "TaskSummary" $ \o -> TaskSummary
        <$> o .:  "task_id"
        <*> o .:  "n_branches"
        <*> o .:  "n_tests"
        <*> o .:? "popen_calls" .!= 0
        <*> o .:? "assertion_distribution" .!= Map.empty
        <*> o .:? "invocation_patterns"    .!= Map.empty
        <*> o .:? "expected_value_samples" .!= []
        <*> o .:? "docstring_samples"      .!= []
        <*> o .:? "test_files"             .!= []

instance ToJSON TaskSummary where
    toJSON s = object
        [ "task_id"                .= tsTaskId s
        , "n_branches"             .= tsNBranches s
        , "n_tests"                .= tsNTests s
        , "popen_calls"            .= tsPopenCalls s
        , "assertion_distribution" .= tsAssertionDistribution s
        , "invocation_patterns"    .= tsInvocationPatterns s
        , "expected_value_samples" .= tsExpectedValueSamples s
        , "docstring_samples"      .= tsDocstringSamples s
        , "test_files"             .= tsTestFiles s
        ]


data ClassifySource = RuleFastPath | LLMFallback
    deriving stock (Eq, Show, Generic)


data ClassifyResult = ClassifyResult
    { crArchetype  :: Archetype
    , crConfidence :: Double
    , crReasons    :: [Text]
    , crSource     :: ClassifySource
    }
    deriving stock (Eq, Show, Generic)


-- The final output of an agent run.
data Belief = Belief
    { bTaskId     :: Text
    , bArchetype  :: Archetype
    , bSummary    :: TaskSummary
    , bClassify   :: ClassifyResult
    , bFindings   :: [Text]      -- list of agent's claims (e.g. discovered subcommands, flag list, error grammar)
    , bConfidence :: Double      -- overall belief confidence
    , bDuration   :: Double      -- seconds spent
    }
    deriving stock (Eq, Show, Generic)

instance ToJSON Belief where
    toJSON b = object
        [ "task_id"    .= bTaskId b
        , "archetype"  .= archetypeName (bArchetype b)
        , "summary"    .= bSummary b
        , "classify"   .= object
            [ "archetype"  .= archetypeName (crArchetype $ bClassify b)
            , "confidence" .= crConfidence (bClassify b)
            , "reasons"    .= crReasons (bClassify b)
            , "source"     .= show (crSource (bClassify b))
            ]
        , "findings"   .= bFindings b
        , "confidence" .= bConfidence b
        , "duration_s" .= bDuration b
        ]
