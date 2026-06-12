{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE DerivingStrategies #-}

-- Minimal Deepseek (OpenAI-compatible) chat completion client.
-- Reads DEEPSEEK_API_KEY from env. Single non-streaming call, no retry yet.
module HaskellTester.LLM.Deepseek
    ( Message (..)
    , ChatRequest (..)
    , callChat
    , defaultRequest
    ) where

import Control.Exception (throwIO, Exception)
import Data.Aeson
import qualified Data.Aeson.KeyMap as KM
import qualified Data.ByteString.Char8 as BS
import qualified Data.ByteString.Lazy as BL
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import qualified Data.Vector as V
import GHC.Generics (Generic)
import Network.HTTP.Client hiding (defaultRequest)
import Network.HTTP.Client.TLS (tlsManagerSettings)
import Network.HTTP.Types.Header (hAuthorization, hContentType)
import Network.HTTP.Types.Status (statusCode)


endpoint :: String
endpoint = "https://api.deepseek.com/chat/completions"


data Message = Message
    { msgRole    :: Text
    , msgContent :: Text
    }
    deriving stock (Show, Generic)

instance ToJSON Message where
    toJSON m = object [ "role" .= msgRole m, "content" .= msgContent m ]


data ChatRequest = ChatRequest
    { reqModel       :: Text
    , reqMessages    :: [Message]
    , reqMaxTokens   :: Int
    , reqTemperature :: Double
    }
    deriving stock (Show, Generic)

instance ToJSON ChatRequest where
    toJSON r = object
        [ "model"       .= reqModel r
        , "messages"    .= reqMessages r
        , "max_tokens"  .= reqMaxTokens r
        , "temperature" .= reqTemperature r
        , "stream"      .= False
        ]


defaultRequest :: [Message] -> ChatRequest
defaultRequest msgs = ChatRequest
    { reqModel       = "deepseek-chat"
    , reqMessages    = msgs
    , reqMaxTokens   = 300
    , reqTemperature = 0.0
    }


newtype DeepseekError = DeepseekError String
    deriving stock Show

instance Exception DeepseekError


-- Extract the assistant message content from a chat completion response.
extractContent :: Value -> Maybe Text
extractContent (Object o) = do
    Array choices  <- KM.lookup "choices" o
    Object choice  <- if V.null choices then Nothing else Just (V.head choices)
    Object message <- KM.lookup "message" choice
    String content <- KM.lookup "content" message
    pure content
extractContent _ = Nothing


-- Send one chat request; return assistant message content.
callChat :: Text -> ChatRequest -> IO Text
callChat apiKey req = do
    mgr     <- newManager tlsManagerSettings
    initial <- parseRequest endpoint
    let httpReq = initial
            { method = "POST"
            , requestHeaders =
                [ (hAuthorization, "Bearer " <> TE.encodeUtf8 apiKey)
                , (hContentType,   "application/json")
                ]
            , requestBody = RequestBodyLBS (encode req)
            }
    resp <- httpLbs httpReq mgr
    let code = statusCode (responseStatus resp)
    if code /= 200
        then throwIO (DeepseekError $ "HTTP " <> show code <> ": "
                                 <> BS.unpack (BL.toStrict (responseBody resp)))
        else case decode (responseBody resp) of
            Nothing -> throwIO (DeepseekError "could not parse JSON response")
            Just v  -> case extractContent v of
                Just t  -> pure t
                Nothing -> throwIO (DeepseekError "no message.content in response")
