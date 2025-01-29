# -*- coding:utf-8 -*-

from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode
from utils.datastore import KnowledgeData
import requests


class KnowledgeBaseImporter:
    def __init__(self):
        self.datastores = {}
        self.current_language = None

    def serialize(self):
        return {key: self.datastores[key].serialize() for key in self.datastores}

    def add_language(self, language, url):
        assert language not in self.datastores, "Language {} already in the data store".format(language)
        self.datastores[language] = KnowledgeData(language, url)
        self.current_language = language

    def load(self, base_url: str):
        raise NotImplementedError('load method must be implemented')

    def process_language(self, url, language):
        raise NotImplementedError('load method must be implemented')

    @property
    def base_url(self):
        return self.datastores[self.current_language].base_url

    def get_url(self, url):
        if url.startswith('http'):
            return url

        if url.startswith('/'):
            last_slash_index = self.base_url.find('/', 9)
            if last_slash_index == -1:
                return self.base_url + url
            return self.base_url[0:self.base_url.find('/', 9)] + url

        return self.base_url + url

    def retrieve(self, url, return_url=False, **kwargs) -> BeautifulSoup:
        url = self.get_url(url)

        r = requests.get(url, **kwargs)
        soup = BeautifulSoup(r.content, features='html.parser')
        if return_url:
            return r.url, soup

        return soup

    def save_category(self, parent_id, entry):
        return self.datastores[self.current_language].add_category(parent_id, **entry)

    def save_article(self, category_id, entry):
        if not entry['previous_url'].startswith('http'):
            entry['previous_url'] = self.get_url(entry['previous_url'])
        identifier = self.datastores[self.current_language].add_article(**entry)
        self.add_article_to_category(identifier, category_id)
        return identifier

    def add_article_to_category(self, article_id, category_id):
        self.datastores[self.current_language].add_article_to_category(article_id, category_id)

    def set_metadata(self, metadata):
        self.datastores[self.current_language].set_metadata(metadata)

    def add_header_link(self, title, url):
        self.datastores[self.current_language].add_link('header', title, url)

    def add_footer_link(self, title, url):
        self.datastores[self.current_language].add_link('footer', title, url)

    def _video_no_cookie(self, url):
        if not url:
            return url

        parsed_url = urlparse(url)
        if parsed_url.netloc in ('www.youtube.com', 'youtube.com', 'youtu.be', 'www.youtu.be'):
            parsed_url = parsed_url._replace(netloc='www.youtube-nocookie.com')
        elif parsed_url.netloc in ('player.vimeo.com', 'vimeo.com'):
            params = parse_qs(parsed_url.query)
            params['dnt'] = 1
            parsed_url = parsed_url._replace(query=urlencode(params))
        elif parsed_url.netloc in ('fast.wistia.net', 'fast.wistia.com', 'wistia.net', 'wistia.com'):
            params = parse_qs(parsed_url.query)
            params['doNotTrack'] = 'true'
            parsed_url = parsed_url._replace(query=urlencode(params))
        elif parsed_url.netloc in ('loom.com', 'www.loom.com'):
            # Loom doesn't support yet ...
            pass

        return parsed_url.geturl()

    def wrap_image_figure(self, item, soup):
        for k in ('class', 'fetchpriority', 'height', 'width', 'sizes', 'srcset', 'loading'):
            if k in item.attrs:
                del item[k]

        if not item.get('alt'):
            del item['alt']

        if item.parent.name in ('p', 'div', 'span') and not item.parent.text.strip():
            item.parent.unwrap()

        if item.parent.name != 'figure':
            item.wrap(soup.new_tag('figure'))

        item.parent['class'] = ['align--center width--normal']

    def clean_iframe(self, item):
        item['src'] = self._video_no_cookie(item['src'])
        item['allowfullscreen'] = 'allowfullscreen'
        item['allow'] = 'fullscreen; picture-in-picture'
        item['frameborder'] = '0'
        item.parent['class'] = 'video-embed'
        if 'height' in item.attrs:
            del item.attrs['height']
        if 'width' in item.attrs:
            del item.attrs['width']
        if 'loading' in item.attrs:
            del item.attrs['loading']
        if 'type' in item.attrs:
            del item.attrs['type']
