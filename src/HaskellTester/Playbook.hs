{-# LANGUAGE OverloadedStrings #-}

-- Load and parse archetype playbook markdown.
-- Each playbook has the same section structure: "## When this fires", "## Probe layer", etc.
module HaskellTester.Playbook
    ( Playbook (..)
    , loadPlaybook
    , loadEmbeddedPlaybook
    , extractSection
    ) where

import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.IO as TIO
import System.FilePath ((</>))

import HaskellTester.EmbeddedData (embeddedPlaybook)
import HaskellTester.Types


data Playbook = Playbook
    { pbArchetype :: Archetype
    , pbRaw       :: Text         -- full markdown content
    , pbSections  :: [(Text, Text)] -- [(section_heading, section_body)]
    }
    deriving (Show)


-- Load a playbook for the given archetype from `<datadir>/playbooks/<Name>.md`.
-- Kept for backwards compatibility / dev iteration where you want to edit
-- markdown without recompiling.
loadPlaybook :: FilePath -> Archetype -> IO Playbook
loadPlaybook dataDir arch = do
    let path = dataDir </> "playbooks" </> T.unpack (archetypeName arch) <> ".md"
    raw <- TIO.readFile path
    pure Playbook
        { pbArchetype = arch
        , pbRaw       = raw
        , pbSections  = parseSections raw
        }


-- Load a playbook from the binary's embedded data (no disk dependency).
-- This is the production path: ship a single binary with playbooks baked in.
loadEmbeddedPlaybook :: Archetype -> IO Playbook
loadEmbeddedPlaybook arch = case embeddedPlaybook arch of
    Nothing -> error $ "no embedded playbook for archetype " <> T.unpack (archetypeName arch)
    Just raw -> pure Playbook
        { pbArchetype = arch
        , pbRaw       = raw
        , pbSections  = parseSections raw
        }


-- Split markdown by "## " headings. Body of each section is everything until next "##".
parseSections :: Text -> [(Text, Text)]
parseSections txt = go (T.lines txt) Nothing []
  where
    go [] cur acc =
        reverse (finalize cur acc)

    go (line : rest) cur acc
        | "## " `T.isPrefixOf` line =
            let title = T.strip (T.drop 3 line)
                acc'  = finalize cur acc
            in go rest (Just (title, [])) acc'

        | otherwise =
            case cur of
                Just (title, body) -> go rest (Just (title, line : body)) acc
                Nothing            -> go rest Nothing acc

    finalize Nothing acc = acc
    finalize (Just (title, bodyRev)) acc =
        (title, T.unlines (reverse bodyRev)) : acc


-- Return the body of a section by case-insensitive heading match.
-- Used by inner loop to pull just "## Probe layer" or "## Verify layer".
extractSection :: Text -> Playbook -> Maybe Text
extractSection heading pb =
    let needle = T.toLower (T.strip heading)
        match (h, _) = needle `T.isPrefixOf` T.toLower h
    in snd <$> lookup' match (pbSections pb)
  where
    lookup' p xs = case filter p xs of
        (x : _) -> Just x
        []      -> Nothing
