{-# LANGUAGE OverloadedStrings #-}

-- Hybrid classifier: rule fast-path first, LLM fallback when confidence is low.
module HaskellTester.Classifier.Hybrid (classify) where

import qualified HaskellTester.Classifier.LLM  as LLM
import qualified HaskellTester.Classifier.Rule as Rule
import HaskellTester.Types


-- Tasks above this rule-confidence are trusted; below this, escalate to LLM.
-- Matches the Python prototype's HIGH_CONF_THRESHOLD = 0.85.
highConfThreshold :: Double
highConfThreshold = 0.85


classify :: TaskSummary -> IO ClassifyResult
classify s = do
    let ruleResult = Rule.classify s
    if crConfidence ruleResult >= highConfThreshold
        then pure ruleResult
        else LLM.classify s
