#!/bin/bash
source config.txt
export TESTING TWITTER_CONSUMER_KEY TWITTER_CONSUMER_SECRET TWITTER_ACCESS_TOKEN TWITTER_ACCESS_TOKEN_SECRET RSS_URL PHANTOMJS_PATH AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY ENV

export new_title='Warning of more dry wells and sinking ground, California officials tell local agencies their groundwater sustainability plans are flawed.'


python3 rssdiff.py
