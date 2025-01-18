from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.alert import Alert
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from apify_client import ApifyClientAsync
from apify_client._errors import ApifyApiError  # ApifyApiError import 추가
from typing import Optional, Tuple
from google.auth.exceptions import TransportError
from google.oauth2 import service_account

import re
import os
import time
import gspread
import pandas as pd
import traceback
import requests
import json
import backoff

# .env 파일 로드
load_dotenv()

# 환경 변수 사용
# mall_id = os.getenv("MALL_ID")
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
login_page = os.getenv("LOGIN_PAGE")
order_page = os.getenv("ORDER_PAGE")
dashboard_page = os.getenv("DASHBOARD_PAGE")
json_str = os.getenv("JSON_STR")
sheet_key = os.getenv("SHEET_KEY")
apify_token = os.getenv("APIFY_TOKEN")
actor_insta_profile = os.getenv("ACTOR_PROFILE_INSTA").strip('"').strip()
actor_insta_post = os.getenv("ACTOR_POST_INSTA").strip('"').strip()
actor_youtube_channel = os.getenv("ACTOR_YOUTUBE_CHANNEL").strip('"').strip()
actor_youtube_video = os.getenv("ACTOR_YOUTUBE_VIDEO").strip('"').strip()
actor_tiktok = os.getenv("ACTOR_TIKTOK").strip('"').strip()
actor_twitter = os.getenv("ACTOR_TWITTER").strip('"').strip()
store_api_key = os.getenv("STORE_API_KEY").strip('"').strip()
store_basic_url = os.getenv("STORE_BASIC_URL").strip('"').strip()
make_hook_url = os.getenv("MAKE_HOOK_URL")

print()
print(f"google: {json_str[:20]}")
print()
print(f"sheet: {sheet_key[:10]}")
print()

class SocialMediaValidator:
    def __init__(self, apify_token: str, actor_id: str):
        self.client = ApifyClientAsync(apify_token)
        self.actor_id = actor_id

    async def validate_profile(self, profile_input: str):
        raise NotImplementedError("Each platform must implement validate_profile")

    async def validate_post(self, post_url: str):
        raise NotImplementedError("Each platform must implement validate_post")

    async def get_recent_posts(self, username: str):
        raise NotImplementedError("Each platform must implement get_recent_posts")


# Youtube Validator

class YoutubeValidator(SocialMediaValidator):
    def __init__(self, apify_token: str, actor_id: str):
        super().__init__(apify_token, actor_id)
        
        # URL 패턴 정의
        self.VIDEO_PATTERNS = [
            r'youtube\.com/watch\?v=[\w-]+',
            r'youtu\.be/[\w-]+',
            r'youtube\.com/embed/[\w-]+',
            r'youtube\.com/v/[\w-]+'
        ]
        
        self.CHANNEL_PATTERNS = [
            r'youtube\.com/channel/([\w-]+)',
            r'youtube\.com/c/([\w-]+)',
            r'youtube\.com/@([\w-]+)'
        ]

        self.COMMENT_PATTERNS = [
            r'youtube\.com/watch\?v=[\w-]+&lc=[\w-]+',  # 일반 댓글
            r'youtube\.com/watch\?v=[\w-]+.*&lc=[\w-]+',  # 다른 파라미터가 있는 경우
        ]

    def validate_url(self, url: str) -> Tuple[bool, Optional[str]]:
        """URL의 유효성을 검사하고 URL 유형을 반환합니다."""
        if not url:
            return False, "URL이 비어있습니다."

        url = url.strip().lower()
        
        # 기본 URL 형식 검사
        if not self._is_valid_base_url(url):
            return False, "유효하지 않은 YouTube URL 형식입니다."

        # 비디오 URL 검사
        if self._is_video_link(url):
            return True, "video"
        
        # 채널 URL 검사
        if self._is_channel_link(url):
            return True, "channel"

        return False, "지원되지 않는 YouTube URL 형식입니다."

    def _is_valid_base_url(self, url: str) -> bool:
        """기본 URL 형식이 유효한지 검사"""
        return ('youtube.com' in url or 'youtu.be' in url) and url.startswith(('http://', 'https://'))

    def _is_video_link(self, url: str) -> bool:
        """비디오 URL인지 검사"""
        return any(re.search(pattern, url) for pattern in self.VIDEO_PATTERNS)

    def _is_channel_link(self, url: str) -> bool:
        """채널 URL인지 검사"""
        return any(re.search(pattern, url) for pattern in self.CHANNEL_PATTERNS)
    
    def _is_comment_link(self, url: str) -> bool:
        '''댓글 URL인지 검사'''
        return any(re.search(pattern, url) for pattern in self.COMMENT_PATTERNS)

    def _extract_channel_id(self, url: str) -> Optional[str]:
        """채널 ID를 추출"""
        if not url:
            return None
        
        if 'youtube.com' not in url:
            return url
            
        try:
            for pattern in self.CHANNEL_PATTERNS:
                match = re.search(pattern, url)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"Channel ID extraction error: {e}")
        return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        """비디오 ID를 추출합니다."""
        try:
            if 'youtube.com/watch?v=' in url:
                return url.split('watch?v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                return url.split('youtu.be/')[1].split('?')[0]
        except Exception as e:
            print(f"Video ID extraction error: {e}")
        return None

    async def validate_channel(self, channel_url: str):
        print('channel_url0', channel_url)
        try:
            channel_id = self._extract_channel_id(channel_url)
            if not channel_id:
                return [False, []]

            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "startUrls": [{"url": channel_url}],
                    "maxResults": 10,
                    "maxResultsShorts": 0,
                    "maxResultStreams": 0,
                }
            )
            
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            # print(dataset_items)
            items = dataset_items.items
            if 'note' in items[0]:
                return [False, items]
            return [len(items) > 0 and not items[0].get('error'), items]
            
        except Exception as e:
            print(f"Channel validation error: {str(e)}")
            traceback.print_exc()
            return [False, []]

    async def validate_video(self, video_url: str):
        try:
            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "searchQueries": [],
                    "maxResults": 10,
                    "maxResultsShorts": 0,
                    "maxResultStreams": 0,
                    "startUrls": [
                        {"url": video_url},
                    ],
                    "subtitlesLanguage": "any",
                    "subtitlesFormat": "srt",
                }
            )
            
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            # print(dataset_items)
            items = dataset_items.items
            if 'note' in items[0]:
                return [False, items]
            return [len(items) > 0 and not items[0].get('error'), items]
            
        except Exception as e:
            print(f"Video validation error: {str(e)}")
            traceback.print_exc()
            return [False, []]

# Tiktok Validator
class TiktokValidator(SocialMediaValidator):
    def __init__(self, apify_token: str, actor_id: str):
        super().__init__(apify_token, actor_id)

    def _is_video_link(self, url: str) -> bool:
        return 'tiktok.com' in url and '/video/' in url

    def _extract_username(self, url: str) -> str:
        if not url:
            return None
        
        if 'tiktok.com' not in url:
            return url
            
        try:
            if '@' in url:
                return url.split('@')[1].split('/')[0].split('?')[0]
        except Exception as e:
            print(f"Username extraction error: {e}")
        return None

    async def validate_profile(self, profile_url: str) -> bool:
        try:
            username = self._extract_username(profile_url)
            if not username:
                return False

            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "profiles": [username],
                    "resultsLimit": 1
                }
            )
            
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            items = dataset_items.items
            return len(items) > 0 and not items[0].get('error')
            
        except Exception as e:
            print(f"Profile validation error: {str(e)}")
            traceback.print_exc()
            return False

    async def validate_post(self, video_url: str) -> bool:
        try:
            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "videoUrls": [video_url],
                    "resultsLimit": 1
                }
            )
            
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            items = dataset_items.items
            return len(items) > 0 and not items[0].get('error')
            
        except Exception as e:
            print(f"Video validation error: {str(e)}")
            traceback.print_exc()
            return False

# Twitter Validator
class TwitterValidator(SocialMediaValidator):
    def __init__(self, apify_token: str, actor_id: str):
        super().__init__(apify_token, actor_id)

    def _is_tweet_link(self, url: str) -> bool:
        return 'twitter.com' in url and '/status/' in url

    def _extract_username(self, url: str) -> str:
        if not url:
            return None
        
        if 'twitter.com' not in url:
            return url
            
        try:
            username = url.split('twitter.com/')[1].split('/')[0]
            return username
        except Exception as e:
            print(f"Username extraction error: {e}")
        return None

    async def validate_profile(self, profile_url: str) -> bool:
        try:
            username = self._extract_username(profile_url)
            if not username:
                return False

            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "usernames": [username],
                    "resultsLimit": 1
                }
            )
            
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            items = dataset_items.items
            return len(items) > 0 and not items[0].get('error')
            
        except Exception as e:
            print(f"Profile validation error: {str(e)}")
            traceback.print_exc()
            return False

    async def validate_post(self, tweet_url: str) -> bool:
        try:
            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "tweetUrls": [tweet_url],
                    "resultsLimit": 1
                }
            )
            
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            items = dataset_items.items
            return len(items) > 0 and not items[0].get('error')
            
        except Exception as e:
            print(f"Tweet validation error: {str(e)}")
            traceback.print_exc()
            return False

# Instagram Validator
class InstagramValidator(SocialMediaValidator):
    def __init__(self, apify_token: str, actor_id: str):
        super().__init__(apify_token, actor_id)

    def _is_profile_card_link(self, url: str) -> bool:
        return 'profile_card' in url or 'profilecard' in url

    def _is_post_link(self, url: str) -> bool:
        return '/p/' in url or '/reel/' in url or '/share/' in url
    
    def _is_tag_username(self, url: str) -> bool:
        return '@' in url
    
    def _is_comment_link(self, url: str) -> bool:
        return '/c/' in url

    def _extract_username(self, url: str) -> str:
        if not url:
            return None
        
        if 'instagram.com' not in url:
            return url
        
        try:
            username = url.split('instagram.com/')[1].split('/')[0].split('?')[0]
            if username == 'p' or username == 'reel':
                return None
            else:
                return username
        except Exception as e:
            print(f"Username extraction error: {e}")
            return None

    async def validate_profile(self, profile_input: str):
        try:
            username = self._extract_username(profile_input)
            if not username:
                return False
                
            print(f"Validating profile for username: {username}")
            
            # Actor 실행 및 완료 대기
            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "usernames": [username],
                    "resultsLimit": 1
                }
            )
            
            # 데이터셋에서 결과 가져오기
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            items = dataset_items.items
            print()
            print('validate_profile 결과')
            print(items[0].get("inputUrl"))
            print()
            return [len(items) > 0 and not items[0].get('error'), items]
            
        except Exception as e:
            print(f"Profile validation error: {str(e)}")
            traceback.print_exc()
            return [False, '']

    async def validate_post(self, post_url: str):
        try:
            print(f"Validating post URL: {post_url}")

            run = await self.client.actor(actor_insta_post).call(
                run_input={
                    "directUrls": [post_url],
                    "resultsType": "posts",
                    "resultsLimit": 1,
                    "addParentData": False
                }
            )

            # 데이터셋에서 결과 가져오기
            dataset_items = await self.client.dataset(run["defaultDatasetId"]).list_items()
            items = dataset_items.items
            print(f"Post validation result: {items[0].get('inputUrl')}")
        
            # 게시물이 존재하고 error가 없는 경우 True
            is_valid = len(items) > 0 and not any(item.get('error') for item in items)
            print(f"Post exists: {is_valid}")
            return [is_valid, items]
                
        except Exception as e:
            print(f"Post validation error: {str(e)}")
            traceback.print_exc()
            return [False, items]
                
        except ApifyApiError as e:
            print(f"Apify API error: {str(e)}")
            traceback.print_exc()
            return [False, items]

    async def get_recent_posts(self, username: str):
        try:
                        
            # Actor 실행 및 완료 대기
            run = await self.client.actor(self.actor_id).call(
                run_input={
                    "usernames": [username],
                    "resultsLimit": 1
                }
            )
            
            # 데이터셋에서 결과 가져오기
            dataset_items = await self.client.dataset(run['defaultDatasetId']).list_items()
            items = dataset_items.items
            print()
            print('get_recent_post 결과')
            print(len(items[0].get('latestPosts')))
            print()
            return [len(items) > 0 and not items[0].get('error'), items[0].get('latestPosts')]
            
        except Exception as e:
            print(f"Recent posts fetch error: {str(e)}")
            return [False, '']

class StoreAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = store_basic_url

    def create_order(self, service_id, link, quantity, runs=None, interval=None):

        params = {
            'key': self.api_key,
            'action': 'add',
            'service': service_id,
            'link': link,
            'quantity': quantity
        }

        try:
            response = requests.post(self.base_url, data=params)
            response.raise_for_status()  # HTTP 오류 체크
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"주문 생성 중 오류 발생: {e}")
            raise
    
    # 주문 상태 확인
    def get_order_status(self, order_id):

        params = {
            'key': self.api_key,
            'action': 'status',
            'order': order_id
        }

        try:
            response = requests.post(self.base_url, data=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"주문 상태 확인 중 오류 발생: {e}")
            raise

    # 여러 주문의 상태를 한 번에 확인
    def get_multiple_order_status(self, order_ids):
        """ 
        Args:
            order_ids (list): 주문 ID 리스트
            
        Returns:
            dict: 여러 주문의 상태 정보
        """
        params = {
            'key': self.api_key,
            'action': 'status',
            'orders': ','.join(map(str, order_ids))
        }

        try:
            response = requests.post(self.base_url, data=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"다중 주문 상태 확인 중 오류 발생: {e}")
            raise

    # 계정 잔액을 확인
    def get_balance(self):
        params = {
            'key': self.api_key,
            'action': 'balance'
        }

        try:
            response = requests.post(self.base_url, data=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"잔액 확인 중 오류 발생: {e}")
            raise


# 릴스 링크 유효성 검사
async def validate_instagram_reels(order, profile_validator, post_validator):
    url = order['order_link']
    is_cardlink = profile_validator._is_profile_card_link(url)
    is_link = post_validator._is_post_link(url)

    if is_link:
        is_valid_post = await post_validator.validate_post(url)
        is_valid = is_valid_post[0]
        if is_valid:
            if is_valid_post[1][0].get('type') == 'Video':
                order['validate_url'] = 1
            else:
                print(f"유효하지 않은 릴스입니다: {url}")
                order['validate_url'] = 0
        else:
            print(f"유효하지 않은 게시물입니다: {url}")
            order['validate_url'] = 0
    else:
        if is_cardlink:
            print(f"아이디 또는 프로필카드링크 입니다: {url}")
            url = profile_validator._extract_username(url)
        else:
            print(f"아이디 또는 프로필링크 입니다: {url}")
        is_valid_profile = await profile_validator.validate_profile(url)
        if is_valid_profile[0]:
            print('릴스 프로필 결과')
            print(is_valid_profile[1])
            print('')
            latest_video_post = max(
                (post for post in is_valid_profile[1][0]['latestPosts'] if post['type'] == 'Video'), 
                key=lambda x: x['timestamp']
            )
            if latest_video_post:
                order['order_edit_link'] = latest_video_post['url']
                order['validate_url'] = 1
            else:
                print(f"릴스 게시물이 없습니다.: {url}")
                order['validate_url'] = 0
        else:
            print(f"유효하지 않은 아이디입니다.: {url}")
            order['validate_url'] = 0
    return order


async def validate_instagram_profile(order, profile_validator):
    url = order['order_link']
    print('프로필카드 여부', profile_validator._is_profile_card_link(url), url)
    if profile_validator._is_profile_card_link(url):
        edit_url = profile_validator._extract_username(url)
        print(f"프로필카드링크 {url} 주문으로 다음으로 변경합니다 -> {edit_url}")
        order['order_edit_link'] = edit_url

    if profile_validator._is_tag_username(url):
        edit_url = profile_validator._extract_username(url)
        edit_url = edit_url.replace('@', '')
        print(f"@ 링크 {url} 주문으로 다음으로 변경합니다 -> {edit_url}")
        order['order_edit_link'] = edit_url

    if profile_validator._is_post_link(url):
        print(f"팔로워 주문에 링크 주문을 접수: {url}")
        order['validate_url'] = 0
        return order

    username = profile_validator._extract_username(url)   

    if not username:
        print(f"유효하지 않은 프로필링크 또는 아이디 형식입니다: {url}")
        order['validate_url'] = 0
        return order

    valid_result = await profile_validator.validate_profile(username)

    if not valid_result[0]:
        print(f"존재하지 않는 프로필입니다: {username}")
        order['validate_url'] = 0
        return order
    
    if valid_result[1][0]["private"]:
        print(f"비공개 프로필입니다: {username}")
        order['validate_url'] = 0
        return order
    
    # print('1', order)
    order['validate_url'] = 1
    return order

async def validate_instagram_post(order, profile_validator, post_validator):
    url = order['order_link']
    is_cardlink = profile_validator._is_profile_card_link(url)
    is_link = post_validator._is_post_link(url)

    if is_link:
        is_valid_post = await post_validator.validate_post(url)
        is_valid = is_valid_post[0]
        if is_valid:
            order['validate_url'] = 1
        else:
            print(f"유효하지 않은 게시물입니다: {url}")
            order['validate_url'] = 0
    else:
        if is_cardlink:
            print(f"아이디 또는 프로필카드링크 입니다: {url}")
            url = profile_validator._extract_username(url)
        else:
            print(f"아이디 또는 프로필링크 입니다: {url}")
        is_valid_profile = await profile_validator.validate_profile(url)
        if is_valid_profile[0]:
            print('게시물 프로필 결과')
            valid_url = is_valid_profile[1][0].get("inputUrl")
            valid_followers = is_valid_profile[1][0].get("followersCount")
            print(f"링크:{valid_url}, 팔로워 수:{valid_followers}")
            print('')            
            latest_post = max(is_valid_profile[1][0]['latestPosts'], key=lambda x: x['timestamp'])
            
            order['order_edit_link'] = latest_post['url']
            order['validate_url'] = 1
        else:
            print(f"게시물이 존재하지 않습니다.: {url}")
            order['validate_url'] = 0
    return order


# 유튜브 검증 보조 함수
async def validate_youtube_channel(order, channel_validator, video_validator):
    url = order['order_link']
    if not channel_validator._is_channel_link(url):
        if not channel_validator._is_video_link(url):
            print(f"유효하지 않은 링크입니다: {url}")
            order['validate_url'] = 0
            return order
        else:
            result = await channel_validator.validate_channel(url)
            if result[0]:
                order['order_edit_link'] = result[1][0].get("channelUrl")
                url = result[1][0].get("channelUrl")
            else:
                order['validate_url'] = 0
                return order
                
    is_valid = await channel_validator.validate_channel(url)

    if not is_valid[0]:
        print(f"결과: {is_valid[1]}")
        print(f"유효하지 않은 채널입니다: {url}")
        order['validate_url'] = 0
    else:
        print(f"결과: {is_valid[1]}")
        print(f"유효한 채널입니다: {url}")
        order['validate_url'] = 1
    return order

async def validate_youtube_video(order, channel_validator, video_validator):
    url = order['order_link']

    if not video_validator._is_valid_base_url(url):
        order['validate_url'] = 0
        return order
    if not video_validator._is_video_link(url):
        if not video_validator._is_channel_link(url):
            order['validate_url'] = 0
            return order
        else:
            result = video_validator.validate_video(url)
            if result[0]:
                order['order_edit_link'] = result[1][0].get("url")
                url = result[1][0].get("url")

    is_valid = await video_validator.validate_video(url)
    
    if not is_valid[0]:
        print(f"결과: {is_valid[1]}")
        print(f"유효하지 않은 동영상입니다: {url}")
        order['validate_url'] = 0
    else:
        print(is_valid[1])
        print(f"유효한 동영상입니다: {url}")
        order['validate_url'] = 1
    return order

async def validate_youtube_comment(order, channel_validator, video_validator):
    url = order['order_link']

    if not video_validator._is_video_link(url):
        order['validate_url'] = 0
        return order
    else:
        if not video_validator._is_comment_link(url):
            order['validate_url'] = 0
            return order

    is_valid = await video_validator.validate_video(url)

    if not is_valid[0]:
        print(f"결과: {is_valid[1]}")
        print(f"유효하지 않은 동영상입니다: {url}")
        order['validate_url'] = 0
    else:
        print(is_valid[1])
        print(f"유효한 동영상입니다: {url}")
        order['validate_url'] = 1
    return order


# 틱톡 검증 보조 함수
async def validate_tiktok_profile(order, validator):
    url = order['order_link']
    is_valid = await validator.validate_profile(url)
    order['validate_url'] = 1 if is_valid else 0
    if not is_valid:
        print(f"유효하지 않은 프로필입니다: {url}")

async def process_tiktok_video(order, validator):
    url = order['order_link']
    if validator._is_video_link(url):
        is_valid = await validator.validate_post(url)
        order['validate_url'] = 1 if is_valid else 0
        if not is_valid:
            print(f"유효하지 않은 동영상입니다: {url}")
    else:
        await process_tiktok_profile_for_videos(order, validator)

async def process_tiktok_profile_for_videos(order, validator):
    url = order['order_link']
    username = validator._extract_username(url)
    if not username:
        print(f"유효하지 않은 프로필 URL입니다: {url}")
        order['validate_url'] = 0
        return
    
    if not await validator.validate_profile(username):
        print(f"유효하지 않은 프로필입니다: {url}")
        order['validate_url'] = 0
        return
    
    recent_videos = await validator.get_recent_videos(username)
    if not recent_videos:
        print(f"최근 동영상이 없습니다: {username}")
        order['validate_url'] = 0
        return
    
    order['order_link'] = recent_videos[0].get('url')
    order['validate_url'] = 1

# 트위터 검증 보조 함수
async def validate_twitter_profile(order, validator):
    url = order['order_link']
    is_valid = await validator.validate_profile(url)
    order['validate_url'] = 1 if is_valid else 0
    if not is_valid:
        print(f"유효하지 않은 프로필입니다: {url}")

async def process_twitter_tweet(order, validator):
    url = order['order_link']
    if validator._is_tweet_link(url):
        is_valid = await validator.validate_post(url)
        order['validate_url'] = 1 if is_valid else 0
        if not is_valid:
            print(f"유효하지 않은 트윗입니다: {url}")
    else:
        await process_twitter_profile_for_tweets(order, validator)

async def process_twitter_profile_for_tweets(order, validator):
    url = order['order_link']
    username = validator._extract_username(url)
    if not username:
        print(f"유효하지 않은 프로필 URL입니다: {url}")
        order['validate_url'] = 0
        return
    
    if not await validator.validate_profile(username):
        print(f"유효하지 않은 프로필입니다: {url}")
        order['validate_url'] = 0
        return
    
    recent_tweets = await validator.get_recent_tweets(username)
    if not recent_tweets:
        print(f"최근 트윗이 없습니다: {username}")
        order['validate_url'] = 0
        return
    
    order['order_link'] = recent_tweets[0].get('url')
    order['validate_url'] = 1



# if not os.path.exists(json_key_path):
#     print(f"JSON 키 파일이 존재하지 않습니다: {json_key_path}")

class GoogleSheetManager:
    def __init__(self):
        self.gc = None
        self.doc = None
        self.initialize_connection()

    @backoff.on_exception(
        backoff.expo,
        (TransportError, requests.exceptions.RequestException),
        max_tries=5
    )
    def initialize_connection(self):
        try:
            print("JSON 문자열 확인:")
            print(f"Length: {len(json_str)}")
            print(f"First part: {json_str[:100]}...")
            print(f"Contains private_key: {'private_key' in json_str}")
        
            credentials_info = json.loads(json_str)
            # print(credentials_info)
            # private_key 형식 보정
            if 'private_key' in credentials_info:
                pk = credentials_info['private_key']
                # 실제 줄바꿈으로 변환
                pk = pk.replace('\\n', '\n')
                credentials_info['private_key'] = pk
            
            print("JSON 파싱 성공")
            print("private_key 시작 부분:", credentials_info.get('private_key', ''))
            print(1)
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            print(2)
            self.gc = gspread.authorize(credentials)
            print(3)
            self.doc = self.gc.open_by_key(sheet_key)
            print(4)
        except Exception as e:
            print(f"연결 초기화 실패: {e}")
            raise

    def get_worksheet(self, sheet_name):
        try:
            return self.doc.worksheet(sheet_name)
        except Exception as e:
            print(f"get_worksheet 실패: {e}")
            self.initialize_connection()  # 연결 재시도
            return self.doc.worksheet(sheet_name)

    @backoff.on_exception(
        backoff.expo,
        (TransportError, requests.exceptions.RequestException),
        max_tries=5
    )
    def get_sheet_data(self, sheet_name):
        worksheet = self.get_worksheet(sheet_name)
        try:
            header = worksheet.row_values(1)
            data = worksheet.get_all_records()

            if not data:
                df = pd.DataFrame(columns=header)
            else:
                df = pd.DataFrame(data)
            
            return df
        except Exception as e:
            print(f"시트 데이터 가져오기 실패: {e}")
            raise

sheet_manager = GoogleSheetManager()

service_sheets = sheet_manager.get_worksheet('market_service_list')
order_sheets = sheet_manager.get_worksheet('market_store_order_list')
manual_order_sheets = sheet_manager.get_worksheet('manual_order_list')

service_sheet = sheet_manager.get_sheet_data('market_service_list')


def get_service_number(df, service_name: str, detail_option: str):
    """
    주어진 서비스 이름과 세부 선택에 일치하는 서비스 번호를 반환합니다.
    :param df: DataFrame, 구글 시트에서 불러온 데이터
    :param service_name: str, 서비스 이름
    :param detail_option: str, 세부 선택 (비어 있을 수 있음)
    :return: str, 일치하는 서비스 번호 (없을 경우 None 반환)
    """

    filtered_row = df[
        (df['서비스유무'] == 1) &  # 서비스 유무가 1인 경우만
        (df['서비스이름'] == service_name) &  # 서비스 이름이 일치
        (df['세부선택'] == detail_option)  # 세부 선택이 일치
    ]

    # 결과 반환
    if not filtered_row.empty:
        result = filtered_row.iloc[0]['서비스번호']  # 첫 번째 일치하는 값 반환
        # print(f"반환할 서비스 번호: {result}, 타입: {type(result)}")
        return result
    return -1  # 일치하는 값이 없으면 None 반환

def add_order_sheet(df, order):
    print()
    try:
        row_data = [
            str(order.get('market_order_num', '')),
            str(order.get('store_order_num', '').get('order')),
            str(order.get('order_username', '')),
            str(order.get('service_num', '')),
            str(order.get('order_link', '')),
            str(order.get('order_edit_link', '')),
            str(order.get('quantity', '')),
            str(order.get('service_name', '')),
            str(order.get('order_time', '')),
            "배송중",
        ]
        df.append_row(row_data)
        print(f"주문 정보가 시트에 추가되었습니다: {row_data}")
        return order

    
    except Exception as e:
        print(f"시트 추가 중 오류 발생: {str(e)}")
        traceback.print_exc()

# 1. Selenium WebDriver 설정
def init_driver():
    chrome_options = Options()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-software-rasterizer')
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# 2. Cafe24 로그인
def cafe24_login(driver, login_page, wait):
    driver.get(login_page)
    try:
        wait.until(EC.all_of(
            EC.presence_of_element_located((By.NAME, "loginId")),
            EC.presence_of_element_located((By.NAME, "loginPasswd"))
        ))
        driver.find_element(By.NAME, "loginId").send_keys(username)  # Admin ID 입력
        driver.find_element(By.NAME, "loginPasswd").send_keys(password)  # 비밀번호 입력
        try:
            login_btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.btnStrong.large")))
            driver.execute_script("arguments[0].click();", login_btn)
            pw_change_btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#iptBtnEm")))
            driver.execute_script("arguments[0].click();", pw_change_btn)
            wait.until(EC.url_to_be(dashboard_page))
        except Exception as e:
            print(f"클릭 중 오류 발생: {e}")
    except TimeoutException:
        print("10초 동안 버튼이 클릭 가능한 상태가 되지 않았습니다.")
    return driver

def get_od_info(order):
    # print('order', order)
    order_options = order.split('\n')
    if len(order_options) > 1:
        order_service = order_options[0].split(' : ')[1].strip()
        order_url = order_options[1].split(' : ')[1].strip()
        return [order_url, order_service]
    else:
        order_url = order_options[0].split(' : ')[1].strip()
        return [order_url, '']


# 3. 배송준비중 주문 정보 크롤링
def scrape_orders(driver, order_page, wait):
    driver.get(order_page)

    # 주문 정보 크롤링
    orders = []
    order_list = []

    try:
        result = wait.until(EC.any_of(
            # 첫 번째 조건: '검색된 주문내역이 없습니다' 메시지
            EC.presence_of_element_located((
                By.XPATH, 
                "//td[@colspan='13'][contains(text(), '검색된 주문내역이 없습니다.')]"
            )),
            # 두 번째 조건: 모든 필요한 요소들이 존재
            EC.all_of(
                # 모든 조건을 만족하는 요소를 찾는다
                EC.presence_of_element_located((By.CSS_SELECTOR, ".w220.left")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".w120.orderNum")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".w30.right")),
            )
        ))
    except TimeoutException:
        print("20초 동안 어떤 조건도 만족하지 않았습니다.")
        return [[], '']

    order_element = driver.find_element(By.CSS_SELECTOR, "#shipedReadyList")
    eship_element = driver.find_element(By.CSS_SELECTOR, "#eShipStartBtn")
    orders = order_element.find_elements(By.TAG_NAME, "tbody")
    
    if not isinstance(result, list):
        return [[], eship_element]

    for order in orders:
        sub_orders = order.find_elements(By.TAG_NAME, "tr")

        if len(sub_orders) == 1:
            # print('한개')
            print()
            order = sub_orders[0]
            try:
                order_option = order.find_element(By.CSS_SELECTOR, ".w220.left")
            except NoSuchElementException:
                continue
            try:
                order_chk = order.find_element(By.CSS_SELECTOR, ".chkbox")
            except NoSuchElementException:
                print('no chkbox')

            p = order_option.find_element(By.TAG_NAME, "p")
            service_name = p.find_elements(By.TAG_NAME, "a")[1].text.split('(P')[0].strip()
            order_detail = order_option.find_element(By.CSS_SELECTOR, ".etc")
            order_username = order.find_element(By.CSS_SELECTOR, ".w80")
            order_time = order.find_element(By.CSS_SELECTOR, ".w65")
            order_num = order.find_element(By.CSS_SELECTOR, ".w120.orderNum")
            order_cnt = order.find_element(By.CSS_SELECTOR, ".w30.right")
            order_info = get_od_info(order_detail.text)
            service = get_service_number(df=service_sheet, service_name=service_name, detail_option=order_info[1])

            if service == 0 or service is None:
                continue
            else:
                # print('serivce', service)
                service_num = str(service)

            order_list.append({
                "market_order_num": order_num.text.split('\n')[0],
                "order_username": order_username.textsplit('[')[0],
                "service_num": str(service_num),
                "quantity": order_cnt.text.replace(',', ''),
                "order_link": order_info[0],
                "order_edit_link": -1,
                "order_time": order_time.text.replace('\\n', ', '),
                "check_element": order_chk,
                "service_name": service_name,
                "store_order_num": {'order': -1},
                "note": '',
                "validate_url": -1
            })
        else:
            for i, sub_order in enumerate(sub_orders):
                try:
                    order_option = sub_order.find_element(By.CSS_SELECTOR, ".w220.left")
                except NoSuchElementException:
                    continue
                try:
                    order_chk = sub_order.find_element(By.CSS_SELECTOR, ".chkbox")
                except NoSuchElementException:
                    print('no chkbox')

                p = order_option.find_element(By.TAG_NAME, "p")
                service_name = p.find_elements(By.TAG_NAME, "a")[1].text.split('(')[0].strip()
                order_detail = order_option.find_element(By.CSS_SELECTOR, ".etc")
                order_username = order.find_element(By.CSS_SELECTOR, ".w80")
                order_time = order.find_element(By.CSS_SELECTOR, ".w65")
                order_num_text = order.find_element(By.CSS_SELECTOR, ".w120.orderNum").text
                order_num = order_num_text.split('\n')[0]
                order_cnt = sub_order.find_element(By.CSS_SELECTOR, ".w30.right")
                order_info = get_od_info(order_detail.text)

                service = get_service_number(df=service_sheet, service_name=service_name, detail_option=order_info[1])
                if service == 0 or service is None:
                    continue
                else:
                    # print('serivce', service)
                    service_num = service

                order_list.append({
                    "market_order_num": f"{order_num}-{i+1}",
                    "order_username": order_username.text.split('[')[0],
                    "service_num": str(service_num),
                    "quantity": order_cnt.text.replace(',', ''),
                    "order_link": order_info[0],
                    "order_edit_link": -1,
                    "order_time": order_time.text.replace('\\n', ', '),
                    "check_element": order_chk,
                    "service_name": service_name,
                    "store_order_num": {'order': -1},
                    "note": '',
                    "validate_url": -1,
                })

    print('주문 목록 작성 완료')
    print('주문수량', len(orders))
    print('스크랩 주문', order_list)
    return [order_list, eship_element]


async def check_order_url(orders,
            instagram_profile_validator,
            instagram_post_validator,
            youtube_channel_validator,
            youtube_video_validator,
            tiktok_validator,
            twitter_validator):

    manual_orders = []
    processed_orders = []

    print('스크랩 주문', orders)

    for order in orders:
        url = None
        try:
            service_num = int(order['service_num'])
            url = order['order_link']
            
            # 서비스 이름 조회
            filtered_row = service_sheet[service_sheet['서비스번호'] == service_num]
            # print(filtered_row)
            if filtered_row.empty:
                print(f"서비스 번호 {service_num}이 시트에 존재하지 않습니다.")
                order['validate_url'] = 0
                manual_orders.append(order)
                continue

            service_row = filtered_row.iloc[0]
            service_name = service_row['서비스이름']
            
            # 인스타그램 서비스 처리
            if '인스타그램' in service_name:
                if '팔로워' in service_name:
                    # 팔로워 서비스 검증
                    order = await validate_instagram_profile(order, instagram_profile_validator)
                    print('팔로워 서비스 링크 검증결과', order.get('inputUrl'))
                
                elif '릴스 조회수' in service_name:
                    # 릴스 조회수 검증
                    order = await validate_instagram_reels(order, instagram_profile_validator, instagram_post_validator)
                    print('릴스 조회수 링크 검증 결과', order.get('inputUrl'))
                    # print('릴스 조회수')
                    # print(order)
                    # print()
                
                elif '커스텀 댓글' in service_name:
                    order['validate_url'] = 0
                    order['note'] = '커스텀 댓글 주문으로 수동 주문이 필요합니다.'
                
                else:
                    order = await validate_instagram_post(order, instagram_profile_validator, instagram_post_validator)

            
            # 유튜브 서비스 처리
            elif '유튜브' in service_name:
                if '구독자' in service_name:
                    # 구독자 서비스는 채널 검증
                    order = await validate_youtube_channel(order, youtube_channel_validator, youtube_video_validator)
                elif '댓글 좋아요' in service_name:
                    order = await validate_youtube_comment(order, youtube_channel_validator, youtube_video_validator)
                else:
                    # 기타 유튜브 서비스는 동영상 검증
                    order = await validate_youtube_video(order, youtube_channel_validator, youtube_video_validator)
            
            # 틱톡 서비스 처리
            elif '틱톡' in service_name:
                # if '팔로워' in service_name:
                #     is_valid = await tiktok_validator.validate_profile(url)
                #     order['validate_url'] = 1 if is_valid else 0
                #     if not is_valid:
                #         print(f"유효하지 않은 프로필입니다: {url}")
                # else:
                #     is_valid = await tiktok_validator.validate_post(url)
                #     order['validate_url'] = 1 if is_valid else 0
                #     if not is_valid:
                #         print(f"유효하지 않은 동영상입니다: {url}")
                order['validate_url'] = 0
                order['note'] = '틱톡 서비스 주문입니다.'

            
            # 트위터 서비스 처리
            elif '트위터' in service_name:
                # if '팔로워' in service_name:
                #     is_valid = await twitter_validator.validate_profile(url)
                #     order['validate_url'] = 1 if is_valid else 0
                #     if not is_valid:
                #         print(f"유효하지 않은 프로필입니다: {url}")
                # else:
                #     is_valid = await twitter_validator.validate_post(url)
                #     order['validate_url'] = 1 if is_valid else 0
                #     if not is_valid:
                #         print(f"유효하지 않은 트윗입니다: {url}")
                order['validate_url'] = 0
                order['note'] = '트위터 서비스 주문입니다.'
            
            # 기타 서비스
            else:
                order['validate_url'] = 0

            if order['validate_url'] == 1:
                processed_orders.append(order)
            else:
                print('미처리 주문')
                manual_orders.append(order)
        # print(order)
        except Exception as e:
            print(f"주문 처리 중 오류 발생: {url}, 에러: {e}")
            order['validate_url'] = 0
            traceback.print_exc()

    # valid_orders = [order for order in processed_orders if order['validate_url'] == 1]
    print(f"전체 주문 수: {len(orders)}")
    print(f"유효한 주문 수: {len(processed_orders)}")
    print(f"수동처리 필요 주문 수: {len(manual_orders)}")
    print(manual_orders)
    return [processed_orders, manual_orders]


def process_order(order_sheets, orders):
    # API 키 설정
    store_api = StoreAPI(store_api_key)
    cnt = 0
    is_manual_orders = []
    result = [False, orders, is_manual_orders]
    for order in orders:
        order_data = None
        try:
            # 주문 생성
            if order["validate_url"] == 1:
                order_link = order["order_edit_link"] if order["order_edit_link"] != -1 else order["order_link"]
                order_data = store_api.create_order(
                    service_id=order["service_num"],
                    link=order_link,
                    quantity=int(order["quantity"])
                )
                print('주문완료')
                # order_data = 1
                order["store_order_num"] = order_data
                cnt += 1
                add_order_sheet(order_sheets, order)
            else:
                is_manual_orders.append(order)

            print("생성된 주문:", order_data)
            if order_data and order["validate_url"] == 1:
                order["check_element"].click()
            
        except Exception as e:
            print(f"오류 발생: {order, e}")
    time.sleep(10)
    if cnt > 0:
        result = [True, orders, is_manual_orders]
    return result

def process_eship(driver, orders, order_element, alert, wait):
    if orders[0]:
        driver.execute_script("arguments[0].click();", order_element)
        alert = wait.until(EC.alert_is_present())
        alert.accept()
        alert = wait.until(EC.alert_is_present())
        alert.accept()
    return

def alert_manual_orders(hook_url, manual_sheet, orders):

    df = sheet_manager.get_sheet_data(manual_sheet)

    for order in orders:
        order_num = order.get("market_order_num")
        user_info = order.get("order_username").split('\n')
        username = user_info[0]
        user_id = user_info[2]
        order_time = order.get("order_time").split('\n')[1].replace("(", '').replace(")", '')
        order_service = order.get("service_name")

        filtered_manual = df[
            (df['처리상태'] == '처리필요') &  
            (df['마켓주문번호'] == order_num) 
        ]

        if len(filtered_manual) > 0:
            payload = {
                "order_num": order_num,
                "user_id": user_id,
                "username": username,
                "order_time": order_time,
                "order_service": order_service,
            }

            response = requests.post(url=hook_url, json=payload)
            print("응답 상태 코드:", response.status_code)
            print("응답 본문:", response.text)
            print('알람완료')
        else:
            print("알릴 주문이 아닙니다.")
    print('모든 알림 완료')
    return 

# 메뉴얼 주문 시트에 입력
def add_manual_order(manual_order_sheet, orders):

    manual_order_data = sheet_manager.get_sheet_data(manual_order_sheet)
    try:
        for order in orders:
            # 시트에 없을때만 입력하도록 마켓주문번호로 필터
            is_row = manual_order_data[
                (manual_order_data['마켓주문번호'] == order.get("market_order_num"))  # 처리상태가 처리필요인 경우만
            ]

            # 일치하는 주문이 없을때 새로 추가
            if len(is_row) == 0:
                add_manual_order_sheet(manual_order_sheet, order)
                print('수동주문 시트 입력완료', order['note'])
            else:
                print('이미 입력한 주문입니다.')
        print('모든 수동주문 시트 입력완료')
        return

    except Exception as e:
        print(f"시트 추가 중 오류 발생: {str(e)}")
        traceback.print_exc()

# 매 단건주문 시트에 입력
def add_manual_order_sheet(df, order):
    print()
    try:
        row_data = [
            str(order.get('market_order_num', '')),
            str(order.get('store_order_num', '').get('order')),
            str(order.get('order_username', '')),
            str(order.get('service_num', '')),
            str(order.get('order_link', '')),
            str(order.get('order_edit_link', '')),
            str(order.get('quantity', '')),
            str(order.get('service_name', '')),
            str(order.get('order_time', '')),
            "처리필요",
            str(order.get('note', '')),
        ]

        if len(row_data) != 11:  # 컬럼 수와 일치하는지 확인
            raise ValueError(f"Expected 11 columns, got {len(row_data)}")
        
        df.append_row(row_data)
        print(f"수동주문 정보가 시트에 추가되었습니다: {row_data}")
        return order

    
    except Exception as e:
        print(f"시트 추가 중 오류 발생: {str(e)}")
        traceback.print_exc()

async def main():
    driver = init_driver()
    wait = WebDriverWait(driver, timeout=20)
    alert = Alert(driver)
    print(f"APIFY_TOKEN: {apify_token[:2]}...")  # 토큰의 앞부분만 출력
    print(f"ACTOR_INSTA: {actor_insta_profile}")
    instagram_profile_validator = InstagramValidator(apify_token, actor_insta_profile)
    instagram_post_validator = InstagramValidator(apify_token, actor_insta_post)
    youtube_channel_validator = YoutubeValidator(apify_token, actor_youtube_channel)
    youtube_video_validator = YoutubeValidator(apify_token, actor_youtube_video)
    tiktok_validator = TiktokValidator(apify_token, actor_tiktok)
    twitter_validator = TwitterValidator(apify_token, actor_twitter)

    try:
        cafe24_login(driver, login_page, wait)
        order_list = scrape_orders(driver, order_page, wait)
        orders, order_element = order_list
        # processed_orders = [{'market_order_num': '20250105-0000216-1', 'order_username': '용재\n\n3861898251@k\n[일반회원]\n주문 : 4건\n(총5건)', 'service_num': '501', 'quantity': '100', 'order_link': 'gpl_lesson_official', 'order_edit_link': -1, 'order_time': '2025-01-05 20:14:18\n(2025-01-05 20:17:10)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="3555437cf1ad124aa13d34bb0ea77f0a", element="f.73AC566FA7743A50BA2144D195C33346.d.0B482F9F6996D3A3930BC0F62C8B5F41.e.625")>', 'store_order_num': {'order': 214952}, 'validate_url': 1}, {'market_order_num': '20250105-0000201-1', 'order_username': '용재\n\n3861898251@k\n[일반회원]\n주문 : 4건\n(총5건)', 'service_num': '32', 'quantity': '1000', 'order_link': 'gpl_lesson_official', 'order_edit_link': 'https://www.instagram.com/p/DEcK4YPpRJL/', 'order_time': '2025-01-05 20:10:25\n(2025-01-05 20:11:41)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="3555437cf1ad124aa13d34bb0ea77f0a", element="f.73AC566FA7743A50BA2144D195C33346.d.0B482F9F6996D3A3930BC0F62C8B5F41.e.186")>', 'store_order_num': {'order': 214953}, 'validate_url': 1}, {'market_order_num': '20250105-0000195-1', 'order_username': '현재현\n\nwogus4802\n[일반회원]\n(총1건)', 'service_num': '441', 'quantity': '100', 'order_link': 'jae_07hyeon', 'order_edit_link': -1, 'order_time': '2025-01-05 20:10:12\n(2025-01-05 20:11:55)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="3555437cf1ad124aa13d34bb0ea77f0a", element="f.73AC566FA7743A50BA2144D195C33346.d.0B482F9F6996D3A3930BC0F62C8B5F41.e.673")>', 'store_order_num': {'order': 214954}, 'validate_url': 1}, {'market_order_num': '20250105-0000172-1', 'order_username': '용재\n\n3861898251@k\n[일반회원]\n주문 : 4건\n(총5건)', 'service_num': '12', 'quantity': '200', 'order_link': 'gpl_lesson_official', 'order_edit_link': 'https://www.instagram.com/p/DEcK4YPpRJL/', 'order_time': '2025-01-05 20:07:48\n(2025-01-05 20:11:41)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="3555437cf1ad124aa13d34bb0ea77f0a", element="f.73AC566FA7743A50BA2144D195C33346.d.0B482F9F6996D3A3930BC0F62C8B5F41.e.698")>', 'store_order_num': {'order': 214955}, 'validate_url': 1}, {'market_order_num': '20250105-0000162-1', 'order_username': '용재\n\n3861898251@k\n[일반회원]\n주문 : 4건\n(총5건)', 'service_num': '441', 'quantity': '600', 'order_link': '_01_6__', 'order_edit_link': -1, 'order_time': '2025-01-05 20:00:02\n(2025-01-05 20:05:50)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="3555437cf1ad124aa13d34bb0ea77f0a", element="f.73AC566FA7743A50BA2144D195C33346.d.0B482F9F6996D3A3930BC0F62C8B5F41.e.723")>', 'store_order_num': {'order': 214956}, 'validate_url': 1}]
        # orders = [{'market_order_num': '20250105-0000037-1', 'order_username': '이아인\n\nain0117\n[일반회원]\n(총1건)', 'service_num': '441', 'quantity': '100', 'order_link': '@ax._inz', 'order_edit_link': -1, 'order_time': '2025-01-05 01:41:23\n(2025-01-05 01:41:23)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="aec1fe2f1114c204a7f38ef7f63781a3", element="f.5A6331A0EC134EFD7F8B5D5C3632D259.d.06E3BCDD94CF186826E1FCE33451DD04.e.641")>', 'store_order_num': -1, 'validate_url': -1}]
        processed_orders, manual_orders = await check_order_url(
            orders,
            instagram_profile_validator,
            instagram_post_validator,
            youtube_channel_validator,
            youtube_video_validator,
            tiktok_validator,
            twitter_validator
        )
        # return 
        print('------------------------')
        print('자동주문 주문들', processed_orders)
        print('------------------------')
        print('수동주문 주문들', manual_orders)
        print('------------------------')
        check_orders = process_order(order_sheets, processed_orders)
        # manual_orders = [{'market_order_num': '20250110-0000112-1', 'order_username': '영재♡\n\n3872253150@k\n', 'service_num': '12', 'quantity': '50', 'order_link': 'hajihye1982', 'order_edit_link': 'https://www.instagram.com/p/DBdhEZnPJGj/', 'order_time': '2025-01-10 17:47:09\n(2025-01-10 17:47:09)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="c5a5f80fe20c18214854a7951ab3d715", element="f.57885A121AEF3F82D8E94D602B74ACBE.d.4230DDD31AE8E34A936937FB26074F7B.e.637")>', 'service_name': '인스타그램 한국인 좋아요', 'store_order_num': {'order': 218372}, 'validate_url': 1}, {'market_order_num': '20250110-0000112-2', 'order_username': '영재♡\n\n3872253150@k\n', 'service_num': '441', 'quantity': '50', 'order_link': 'hajihye1982', 'order_edit_link': -1, 'order_time': '2025-01-10 17:47:09\n(2025-01-10 17:47:09)', 'check_element': '<selenium.webdriver.remote.webelement.WebElement (session="c5a5f80fe20c18214854a7951ab3d715", element="f.57885A121AEF3F82D8E94D602B74ACBE.d.4230DDD31AE8E34A936937FB26074F7B.e.659")>', 'service_name': '인스타그램 한국인 팔로워', 'store_order_num': {'order': 218373}, 'validate_url': 1}]
        
        if len(manual_orders) > 0:
            add_manual_order(manual_order_sheets, manual_orders)
            alert_manual_orders(make_hook_url, manual_order_sheets, manual_orders)
            print('alert 완')
        process_eship(driver, check_orders, order_element, alert, wait)
        print('process_eship 완')
        
        print('check_orders', check_orders)
        return
        # return
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return []
    finally:
        print('완료')
        driver.quit()
        # 비동기 세션 정리

if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        orders = loop.run_until_complete(main())
    finally:
        loop.close()
