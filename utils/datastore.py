# -*- coding:utf-8 -*-

from slugify import slugify
from uuid import uuid4
import logging


class KnowledgeData(dict):
    def __init__(self, language, url, unique_categories_slug=False, unique_articles_slug=True):
        self._slugs = {
            'categories': [],
            'articles': []
        }
        self.unique_categories_slug = unique_categories_slug
        self.unique_articles_slug = unique_articles_slug

        # Will be exported
        self.base_url = url
        self.language = language
        self.metadata = {}
        self.categories = {}
        self.articles = {}

    def _get_available_slug(self, slug, kind):
        slug = slugify(slug)

        if slug not in self._slugs[kind]:
            self._slugs[kind].append(slug)
            return slug

        index = 1
        while True:
            index += 1
            key = '{}-{}'.format(slug, index)
            if key not in self._slugs[kind]:
                self._slugs[kind].append(key)
                return key

    def _add_to_store(self, key, entry):
        identifier = str(uuid4())
        getattr(self, key)[identifier] = entry
        return identifier

    def serialize(self):
        return {
            'base_url': self.base_url,
            'language': self.language,
            'metadata': self.metadata,
            'categories': self.categories,
            'articles': self.articles
        }

    def set_metadata(self, metadata):
        """
        Expected metadata are:
            * title
            * favicon
            * custom_domain
            * favicon
            * logo
            * accent_color
            * code
            * title
            * description
            * company_name
            * company_url
            * links
        """
        for k in metadata:
            self.metadata[k] = metadata[k]

    def add_category(self, parent_id, title, url=None, icon=None, slug=None, description=None, seo_title=None, seo_description=None):
        assert title is not None, "Title is required"

        if self.unique_categories_slug:
            slug = self._get_available_slug(slug or title, 'categories')
        elif not slug:
            slug = slugify(title)

        identifier = self._add_to_store('categories', {
            'title': title,
            'url': url,
            'slug': slug,
            'icon': icon,
            'description': description,
            'seo_title': seo_title,
            'seo_description': seo_description,
            'parent': parent_id,
            'articles': []
        })

        logging.getLogger('knowledge-base-exporter').info('Added collection: {}'.format(title))
        return identifier

    def add_article(self, title, content, previous_url, slug=None, description=None, seo_title=None, seo_description=None, created=None, last_updated=None):
        assert title is not None, "Title is required"
        assert content is not None, "content is required"
        assert previous_url is not None, "previous_url is required"
        assert previous_url.startswith('http'), "Invalid URL for previous_url"

        if self.unique_articles_slug:
            slug = self._get_available_slug(slug or title, 'articles')
        elif not slug:
            slug = slugify(title)

        if last_updated and not created:
            created = last_updated

        identifier = self._add_to_store('articles', {
            'title': title,
            'content': content,
            'previous_url': previous_url,
            'slug': slug,
            'description': description,
            'seo_title': seo_title,
            'seo_description': seo_description,
            'created': created,
            'last_updated': last_updated
        })

        logging.getLogger('knowledge-base-exporter').info('Added article: {}'.format(title))
        return identifier

    def add_article_to_category(self, article_id, category_id):
        self.categories[category_id]['articles'].append(article_id)
