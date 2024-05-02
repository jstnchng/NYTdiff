#!/usr/bin/python3
import collections
from datetime import datetime
import hashlib
import logging
import os
import sys
import time
import re

import bleach
import imgkit
from PIL import Image, ImageChops
from pytz import timezone
import requests
import tweepy
from simplediff import html_diff
import boto3

import feedparser

TIMEZONE = 'America/Los_Angeles'
LOCAL_TZ = timezone(TIMEZONE)
MAX_RETRIES = 10
RETRY_DELAY = 3
ENV=os.environ['ENV']

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

if ENV == 'local':
    local_path = './'
else:
    output_path = os.path.join('/tmp', 'output')
    os.mkdir(output_path)
    local_path = "/tmp/"


class BaseParser(object):
    def __init__(self, tweepy_v1, tweepy_v2, db):
        self.urls = list()
        self.payload = None
        self.articles = dict()
        self.filename = str()
        self.db = db
        self.tweepy_v1 = tweepy_v1
        self.tweepy_v2 = tweepy_v2

    def test_twitter(self):
        print(self.tweepy_v1.rate_limit_status())
        print(self.tweepy_v1.me().name)

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
            print(response)
            if 'tweet_id' in response['Item'] and int(response['Item']['tweet_id']['N']) > 0:
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
            response = self.tweepy_v1.media_upload(filename)
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
                tweet_id = self.tweepy_v2.create_tweet(
                    text=text, media_ids=images,
                    in_reply_to_tweet_id=reply_to)
            else:
                tweet_id = self.tweepy_v2.create_tweet(
                    text=text, media_ids=images)
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
            tweet_id = self.tweepy_v2.create_tweet(text=text)
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
        image = self.media_upload(local_path + 'output/' + self.filename + '.png')
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

    def add_border(self, bbox):
        return (bbox[0] - 50, bbox[1] - 50, bbox[2] + 50, bbox[3] + 50)

    def resize(self, im):
        desired_width = 400
        desired_height = 223

        img_w, img_h = im.size

        if img_w > desired_width or img_h > desired_height:
            if img_h > img_w/2:
                desired_width = img_h*2
                desired_height = img_h
                print("resize: image is larger than 400, 200. changing width to match height")
            else:
                desired_height = img_w//2
                desired_width = img_w
                print("resize: image is larger than 400, 200. changing height to match width")

        background = Image.new('RGBA', (desired_width, desired_height), (255, 255, 255, 0))
        bg_w, bg_h = background.size
        offset = ((bg_w - img_w) // 2, (bg_h - img_h) // 2)
        background.paste(
            im,
            offset
        )

        return background

    def trim(self, im):
        bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
        diff = ImageChops.difference(im, bg)
        diff = ImageChops.add(diff, diff, 2.0, -100)
        diff = diff.convert('RGB')
        bbox = diff.getbbox()
        border_bbox = self.add_border(bbox)
        cropped_im = im.crop(border_bbox)
        return self.resize(cropped_im)

    def break_html(self, string):
        final = ''
        wrap_length = 40
        char_counter = 0
        current_line_length = 0
        current_line = ''

        words = string.split()
        for word in words:
            current_line += word + ' '
            current_line_length += len(word) + 1
            if current_line_length > wrap_length:
                final += current_line + '<br/>'
                current_line = ''
                current_line_length = 0

        return final + current_line

    def show_diff(self, old, new, img_path):
        if len(old) == 0 or len(new) == 0:
            print('show_diff: Old or New empty')
            logging.info('show_diff: Old or New empty')
            return False
        new_hash = hashlib.sha224(new.encode('utf8')).hexdigest()

        html_diff_str = html_diff(old, new)
        print('show_diff: html_diff str: {}'.format(html_diff_str))
        logging.info(html_diff_str)
        html_diff_break_str = self.break_html(html_diff_str)
        print('show_diff: html_diff str with breaks: {}'.format(html_diff_break_str))
        logging.info(html_diff_str)

        if ENV == 'local':
            css_path = './css/styles.css'
        else:
            css_path = '/var/task/style/css/styles.css'
        html = """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <link rel="stylesheet" href="{}">
          </head>
          <body>
          <p>
          {}
          </p>
          </body>
        </html>
        """.format(css_path, html_diff_break_str)
        tmp_path = local_path + 'tmp.html'
        with open(tmp_path, 'w') as f:
            f.write(html)
        print("html: " + html)

        options = {
            "enable-local-file-access": None
        }
        imgkit.from_file(tmp_path, img_path, options=options)

        im = Image.open(img_path)
        im = self.trim(im)

        timestamp = str(int(time.time()))
        self.filename = timestamp + new_hash

        im.save(local_path + 'output/' + self.filename + '.png')
        return True

    def __str__(self):
        return ('\n'.join(self.urls))


class RSSParser(BaseParser):
    def __init__(self, tweepy_v1, tweepy_v2, rss_url, db):
        BaseParser.__init__(self, tweepy_v1, db)
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

        # testing code
        #  if article_dict['article_id'] == 'https://www.latimes.com/environment/story/2021-12-11/state-cites-flaws-in-san-joaquin-valley-groundwater-plans':
            #  article_dict['abstract'] = os.environ['new_title']

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
            return "New"
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
                return "Existing"
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

                url = data['url']
                img_path = local_path + re.sub(r'\W+', '', data['title']) + '.png'

                if row['url']['S'] != data['url']:
                    if self.show_diff(row['url']['S'], data['url'], img_path):
                        tweet_text = "Change in URL"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')
                if row['title']['S'] != data['title']:
                    if self.show_diff(row['title']['S'], data['title'], img_path):
                        tweet_text = "Change in Headline"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')
                if row['abstract']['S'] != data['abstract']:
                    if self.show_diff(row['abstract']['S'], data['abstract'], img_path):
                        tweet_text = "Change in Abstract"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')
                if row['author']['S'] != data['author']:
                    if self.show_diff(row['author']['S'], data['author'], img_path):
                        tweet_text = "Change in Author"
                        self.tweet(tweet_text, data['article_id'], url,
                                   'article_id')

                data['version'] = row['version']['N'] + 1
                updated_version_data = self.build_version(str(data['version']), data)
                self.db.put_item(
                    TableName='rss_versions',
                    Item=updated_version_data
                )
                
                return "Changed"

    def loop_entries(self, entries):
        if len(entries) == 0:
            print("loop_entries: empty rss feed")
            return False
        results = []
        for article in entries:
            try:
                article_dict = self.entry_to_dict(article)
                if article_dict is not None:
                    result = self.store_data(article_dict)
                    results.append(result)
            except BaseException as e:
                logging.exception('Problem looping RSS: %s', article)
                print ('Exception: {}'.format(str(e)))
                print('***************')
                print(article)
                print('***************')
                raise(e)
        return results

    def parse_rss(self):
        r = feedparser.parse(self.urls[0])
        if r is None:
            print("parse_rss: empty response rss")
            logging.warning('Empty response RSS')
            return
        else:
            print("parse_rss: parsing rss feed: {}".format(r.feed.title))
            logging.info('Parsing %s', r.feed.title)
        results = self.loop_entries(r.entries)
        return results

    def process_results(self, results):
        newNum = 0
        existingNum = 0
        changedNum = 0
        for result in results:
            if result == "New":
                newNum += 1
            if result == "Existing":
                existingNum += 1
            if result == "Changed":
                changedNum += 1
        print("process_results: new articles: {}, unchanged articles: {}, changed articles: {}".format(newNum, existingNum, changedNum))


def lambda_function(event, context):
    main()


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
    auth = tweepy.OAuth1UserHandler(consumer_key, consumer_secret, access_token, access_token_secret)
    tweepy_v1_client = tweepy.API(auth)
    print("main: twitter api tweepy v1 client configured")
    logging.debug('Twitter API tweepy v1 client configured')

    tweepy_v2_client = tweepy.Client(consumer_key, consumer_secret, access_token, access_token_secret)

    aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
    aws_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
    if ENV == 'local':
        db = boto3.client('dynamodb', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)
    else:
        aws_session_token = os.environ['AWS_SESSION_TOKEN']
        db = boto3.client('dynamodb', region_name='us-west-2', aws_session_token=aws_session_token, aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)

    try:
        print('main: starting RSS parse')
        logging.debug('main: starting RSS parse')
        rss_url = os.environ['RSS_URL']
        rss = RSSParser(tweepy_v1_client, tweepy_v2_client, rss_url, db)
        results = rss.parse_rss()
        rss.process_results(results)
        print("main: finished parsing RSS")
        logging.debug('Finished RSS')
    except BaseException as e:
        logging.exception('RSS')
        raise(e)

    print('main: Finished script')
    logging.info('Finished script')


if __name__ == "__main__":
    main()
