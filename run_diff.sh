#!/bin/bash
source config.txt
export TESTING TWITTER_CONSUMER_KEY TWITTER_CONSUMER_SECRET TWITTER_ACCESS_TOKEN TWITTER_ACCESS_TOKEN_SECRET RSS_URL PHANTOMJS_PATH AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY ENV

export new_title='test_title_31'


python3 rssdiff.py
