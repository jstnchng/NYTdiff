#!/usr/bin/python3

import collections
from datetime import datetime
import hashlib
import logging
import os
import sys
import time

import bleach
from PIL import Image
from pytz import timezone
import requests
import tweepy
from simplediff import html_diff
from selenium import webdriver
import boto3

import feedparser

TIMEZONE = 'America/Los_Angeles'
LOCAL_TZ = timezone(TIMEZONE)
MAX_RETRIES = 10
RETRY_DELAY = 3

if 'TESTING' in os.environ:
    if os.environ['TESTING'] == 'False':
        TESTING = False
    else:
        TESTING = True
else:
    TESTING = True

if 'LOG_FOLDER' in os.environ:
    LOG_FOLDER = os.environ['LOG_FOLDER']
else:
    LOG_FOLDER = ''

PHANTOMJS_PATH = os.environ['PHANTOMJS_PATH']


class BaseParser(object):
    def __init__(self, api, db):
        self.urls = list()
        self.payload = None
        self.articles = dict()
        self.current_ids = set()
        self.filename = str()
        self.db = db
        self.api = api

    def test_twitter(self):
        print(self.api.rate_limit_status())
        print(self.api.me().name)

    def get_article_by_id(self, article_id):
        response = self.db.get_item(
            TableName='rss_ids',
            Key={
                'article_id': {
                    'S': article_id
                }
            }
        )

        return response

    def get_prev_tweet(self, article_id, column):
        response = self.get_article_by_id(article_id)

        if response is None or response['Item'] is None:
            return None
        else:
            if 'tweet_id' in response['Item'] and response['Item']['tweet_id']['N'] > 0:
                return response['Item']['tweet_id']['N']
            else:
                return None

    def update_tweet_db(self, article_id, tweet_id, column):
        self.db.update_item(
            TableName='rss_ids',
            Key={
                'article_id': {
                    'S': article_id
                }
            },
            UpdateExpression="set tweet_id=:tweet_id",
            ExpressionAttributeValues={
                ':tweet_id': {
                    'N': str(tweet_id)
                }
            },
            ReturnValues="UPDATED_NEW"
        )
        print('update_tweet_db: updated article_id: {}, new tweet_id: {}'.format(article_id, tweet_id))
        logging.debug('Updated tweet ID in db')

    def media_upload(self, filename):
        if TESTING:
            return 1
        try:
            response = self.api.media_upload(filename)
        except:
            print (sys.exc_info()[0])
            print('media_upload: uploaded new media')
            logging.exception('Media upload')
            return False
        return response.media_id_string

    def tweet_with_media(self, text, images, reply_to=None):
        if TESTING:
            print (text, images, reply_to)
            return True
        try:
            if reply_to is not None:
                tweet_id = self.api.update_status(
                    status=text, media_ids=images,
                    in_reply_to_status_id=reply_to)
            else:
                tweet_id = self.api.update_status(
                    status=text, media_ids=images)
        except:
            print('tweet_with_media: failed')
            logging.exception('Tweet with media failed')
            print (sys.exc_info()[0])
            return False
        return tweet_id

    def tweet_text(self, text):
        if TESTING:
            print(text)
            return True
        try:
            print("tweet_text: sending new tweet")
            tweet_id = self.api.update_status(status=text)
        except:
            print("tweet_text: tweet failed")
            logging.exception('Tweet text failed')
            print (sys.exc_info()[0])
            print (sys.exc_info()[1])
            print (sys.exc_info()[2])
            return False
        return tweet_id

    def tweet(self, text, article_id, url, column='id'):
        images = list()
        image = self.media_upload('./output/' + self.filename + '.png')
        print('tweet: Media: {}, text to tweet: {}, new article id: {}'.format(image, text, article_id))
        logging.info('Media ready with ids: %s', image)
        images.append(image)
        logging.info('Text to tweet: %s', text)
        logging.info('Article id: %s', article_id)

        reply_to = self.get_prev_tweet(article_id, column)
        if reply_to is None:
            print("tweet: tweeting url: {}".format(url))
            logging.info('Tweeting url: %s', url)
            tweet = self.tweet_text(url)
            # if TESTING, give a random id based on time
            reply_to = tweet.id if not TESTING else time.time()
        print('tweet: replying to: {}'.format(reply_to))
        logging.info('Replying to: %s', reply_to)
        tweet = self.tweet_with_media(text, images, reply_to)
        if TESTING:
            # if TESTING, give a random id based on time
            tweet_id = time.time()
        else:
            tweet_id = tweet.id
        print('tweet: Id to store: {}'.format(tweet_id))
        logging.info('Id to store: %s', tweet_id)
        self.update_tweet_db(article_id, tweet_id, column)
        return

    def get_page(self, url, header=None, payload=None):
        for x in range(MAX_RETRIES):
            try:
                r = requests.get(url=url, headers=header, params=payload)
            except BaseException as e:
                if x == MAX_RETRIES - 1:
                    print('get_page: Max retries reached')
                    logging.warning('Max retries for: %s', url)
                    return None
                if '104' not in str(e):
                    print('get_page: Problem with url {}'.format(url))
                    print('get_page: Exception: {}'.format(str(e)))
                    logging.exception('Problem getting page')
                    return None
                time.sleep(RETRY_DELAY)
            else:
                break
        return r

    def strip_html(self, html_str):
        """
        a wrapper for bleach.clean() that strips ALL tags from the input
        """
        tags = []
        attr = {}
        styles = []
        strip = True
        return bleach.clean(html_str,
                            tags=tags,
                            attributes=attr,
                            styles=styles,
                            strip=strip)

    def show_diff(self, old, new):
        if len(old) == 0 or len(new) == 0:
            print('show_diff: Old or New empty')
            logging.info('show_diff: Old or New empty')
            return False
        new_hash = hashlib.sha224(new.encode('utf8')).hexdigest()
        logging.info(html_diff(old, new))
        html = """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <link rel="stylesheet" href="./css/styles.css">
          </head>
          <body>
          <p>
          {}
          </p>
          </body>
        </html>
        """.format(html_diff(old, new))
        with open('tmp.html', 'w') as f:
            f.write(html)

        driver = webdriver.PhantomJS(
            executable_path=PHANTOMJS_PATH + 'phantomjs')
        driver.get('tmp.html')
        e = driver.find_element_by_xpath('//p')
        start_height = e.location['y']
        block_height = e.size['height']
        end_height = start_height
        start_width = e.location['x']
        block_width = e.size['width']
        end_width = start_width
        total_height = start_height + block_height + end_height
        total_width = start_width + block_width + end_width
        timestamp = str(int(time.time()))
        driver.save_screenshot('./tmp.png')
        img = Image.open('./tmp.png')
        img2 = img.crop((0, 0, total_width, total_height))
        if int(total_width) > int(total_height * 2):
            background = Image.new('RGBA', (total_width, int(total_width / 2)),
                                   (255, 255, 255, 0))
            bg_w, bg_h = background.size
            offset = (int((bg_w - total_width) / 2),
                      int((bg_h - total_height) / 2))
        else:
            background = Image.new('RGBA', (total_width, total_height),
                                   (255, 255, 255, 0))
            bg_w, bg_h = background.size
            offset = (int((bg_w - total_width) / 2),
                      int((bg_h - total_height) / 2))
        background.paste(img2, offset)
        self.filename = timestamp + new_hash
        background.save('./output/' + self.filename + '.png')
        return True

    def __str__(self):
        return ('\n'.join(self.urls))


class RSSParser(BaseParser):
    def __init__(self, api, rss_url, db):
        BaseParser.__init__(self, api, db)
        self.urls = [rss_url]

    def entry_to_dict(self, article):
        article_dict = dict()
        article_dict['article_id'] = article.id.split(' ')[0]
        article_dict['url'] = article.link
        article_dict['title'] = article.title_detail.value
        article_dict['abstract'] = self.strip_html(article.summary_detail.value)
        author_name = article.get("author", None)
        if not author_name:
            return None
        article_dict['author'] = author_name

        od = collections.OrderedDict(sorted(article_dict.items()))
        article_dict['hash'] = hashlib.sha224(
            repr(od.items()).encode('utf-8')).hexdigest()
        article_dict['date_time'] = datetime.now(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")
        return article_dict

    def build_version(self, version, data):
        version_data = {
            'version': {
                'N': version,
            },
            'abstract': {
                'S': data['abstract'],
            },
            'url': {
                'S': data['url'],
            },
            'date_time': {
                'S': data['date_time'],
            },
            'title': {
                'S': data['title'],
            },
            'article_id': {
                'S': data['article_id'],
            },
            'hash': {
                'S': data['hash'],
            },
            'author': {
                'S': data['author'],
            },
        }

        return version_data

    def store_data(self, data):
        response = self.get_article_by_id(data['article_id'])

        # New article
        if response.get('Item') is None:
            article = {
                'article_id': {
                    'S': data['article_id'],
                },
                'add_dt': {
                    'S': data['date_time'],
                },
                'status': {
                    'S': 'home',
                },
                'tweet_id': {
                    'N': '-1',
                },
            }

            self.db.put_item(
                TableName='rss_ids',
                Item=article
            )
            print('store_data: New article tracked: {}'.format(data['url']))
            logging.info('New article tracked: %s', data['url'])

            version_data = self.build_version("1", data)
            self.db.put_item(
                TableName='rss_versions',
                Item=version_data
            )
        else:
            # re insert
            count_resp = self.db.query(
                TableName='rss_versions',
                Select='COUNT',
                KeyConditionExpression='article_id = :article_id',
                FilterExpression='#hash = :hash',
                ExpressionAttributeNames={
                    '#hash': 'hash'
                },
                ExpressionAttributeValues={
                    ':article_id': {
                        'S': data['article_id']
                    },
                    ':hash': {
                        'S': data['hash']
                    }
                },
            )
            count = count_resp['Count']

            if count == 1:  # Existing
                print('store_data: article already exists, so skipping')
                pass
            else:  # Changed
                print("store_data: new data in existing article")

                result = self.db.query(
                    TableName='rss_versions',
                    KeyConditionExpression='article_id = :article_id',
                    ExpressionAttributeValues={
                        ':article_id': {
                            'S': data['article_id']
                        },
                    },
                    Limit=1,
                    ScanIndexForward=False
                )

                row = result['Items'][0]

                data['version'] = row['version']['N']
                updated_version_data = self.build_version(str(data['version']), data)
                self.db.put_item(
                    TableName='rss_versions',
                    Item=updated_version_data
                )

                url = data['url']
                if row['url']['S'] != data['url']:
                    if self.show_diff(row['url']['S'], data['url']):
                        tweet_text = "Change in URL"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')
                if row['title']['S'] != data['title']:
                    if self.show_diff(row['title']['S'], data['title']):
                        tweet_text = "Change in Headline"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')
                if row['abstract']['S'] != data['abstract']:
                    if self.show_diff(row['abstract']['S'], data['abstract']):
                        tweet_text = "Change in Abstract"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')
                if row['author']['S'] != data['author']:
                    if self.show_diff(row['author']['S'], data['author']):
                        tweet_text = "Change in Author"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')

    def loop_entries(self, entries):
        if len(entries) == 0:
            print("loop_entries: empty rss feed")
            return False
        for article in entries:
            try:
                article_dict = self.entry_to_dict(article)
                if article_dict is not None:
                    self.store_data(article_dict)
                    self.current_ids.add(article_dict['article_id'])
            except BaseException as e:
                logging.exception('Problem looping RSS: %s', article)
                print ('Exception: {}'.format(str(e)))
                print('***************')
                print(article)
                print('***************')
                return False
        return True

    def parse_rss(self):
        r = feedparser.parse(self.urls[0])
        if r is None:
            print("parse_rss: empty response rss")
            logging.warning('Empty response RSS')
            return
        else:
            print("parse_rss: parsing rss feed: {}".format(r.feed.title))
            logging.info('Parsing %s', r.feed.title)
        self.loop_entries(r.entries)
        # loop = self.loop_entries(r.entries)
        #  if loop:
            #  self.remove_old('article_id')


def main():
    # logging
    logging.basicConfig(filename=LOG_FOLDER + 'titlediff.log',
                        format='%(asctime)s %(name)13s %(levelname)8s: ' +
                        '%(message)s',
                        level=logging.INFO)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.info('Starting script')

    consumer_key = os.environ['TWITTER_CONSUMER_KEY']
    consumer_secret = os.environ['TWITTER_CONSUMER_SECRET']
    access_token = os.environ['TWITTER_ACCESS_TOKEN']
    access_token_secret = os.environ['TWITTER_ACCESS_TOKEN_SECRET']
    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.secure = True
    auth.set_access_token(access_token, access_token_secret)
    twitter_api = tweepy.API(auth)
    print("main: twitter api configured")
    logging.debug('Twitter API configured')

    aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
    aws_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
    db = boto3.client('dynamodb', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)

    try:
        print('main: starting RSS parse')
        logging.debug('main: starting RSS parse')
        rss_url = os.environ['RSS_URL']
        rss = RSSParser(twitter_api, rss_url, db)
        rss.parse_rss()
        print("main: finished parsing RSS")
        logging.debug('Finished RSS')
    except:
        logging.exception('RSS')

    print('main: Finished script')
    logging.info('Finished script')


if __name__ == "__main__":
    main()
