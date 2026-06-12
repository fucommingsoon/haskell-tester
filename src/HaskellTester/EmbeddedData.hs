{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE TemplateHaskell #-}

-- All runtime data files embedded into the binary at compile time.
-- Eliminates the need to ship a separate data/ directory at deployment.
--
-- ANTI-CHEATING BOUNDARY: only meta-method artifacts are embedded:
--   * archetype_taxonomy.json (definitions only)
--   * playbooks/*.md          (strategy templates)
--   * fewshot_examples.json   (abstract signal shapes, task_id stripped)
--
-- NEVER embed task_archetypes.jsonl (ground truth lookup table) or
-- summaries.jsonl (raw grader-derived data).
module HaskellTester.EmbeddedData
    ( embeddedTaxonomy
    , embeddedFewShot
    , embeddedPlaybook
    , listEmbeddedPlaybooks
    ) where

import Data.ByteString (ByteString)
import qualified Data.ByteString as BS
import Data.FileEmbed (embedFile, embedDir)
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE

import HaskellTester.Types


-- The archetype taxonomy as raw JSON bytes.
embeddedTaxonomy :: ByteString
embeddedTaxonomy = $(embedFile "data/archetype_taxonomy.json")


-- The few-shot examples as raw JSON bytes.
embeddedFewShot :: ByteString
embeddedFewShot = $(embedFile "data/fewshot_examples.json")


-- All playbook files as a directory snapshot: [(relative_path, contents)].
embeddedPlaybookDir :: [(FilePath, ByteString)]
embeddedPlaybookDir = $(embedDir "data/playbooks")


-- Fetch a playbook by archetype. Looks up by filename <Archetype>.md.
embeddedPlaybook :: Archetype -> Maybe Text
embeddedPlaybook arch =
    let want = T.unpack (archetypeName arch) <> ".md"
    in TE.decodeUtf8 <$> lookup want embeddedPlaybookDir


listEmbeddedPlaybooks :: [(FilePath, ByteString)]
listEmbeddedPlaybooks = embeddedPlaybookDir
