# -*- coding:utf-8 -*-

from .base import KnowledgeBaseImporter
from slugify import slugify
from utils import requests
import urllib.parse
import datetime, uuid, json


class Notion(KnowledgeBaseImporter):
    def retrieve(self, url: str):
        url_uuid = url.split('-')[-1]
        parsed_uuid = str(uuid.UUID(url_uuid))

        base_url = url[0:url.find('/', 9)]
        url = base_url + '/api/v3/loadCachedPageChunk'
        r = requests.post(
            url,
            json={
                'page': {
                    'id': parsed_uuid
                },
                'limit': 100,
                'cursor': {
                    'stack': []
                },
                'chunkNumber': 0,
                'verticalColumns': False
            }
        )

        assert r.status_code == 200
        return url, r.json['recordMap']

    def load(self, base_url: str, language=None):
        self.add_language('en', base_url[0:base_url.find('/', 9)])
        body = self.retrieve(self.base_url)

        # Listing the categories
        for block in body['collection_view'].values():
            assert block['role'] == 'reader', "Type is not reader"
            if block['value']['type'] != 'gallery':
                continue

            assert block['value']['alive'], "Block is not alive!"

            root_collection_id = None
            for collection_id in block['value']['page_sort']:
                collection = self.retrieve(base_url[0:base_url.rfind('-')] + '-' + collection_id.replace('-', ''))

                # Searching the root page
                for colblock in collection.get('block', {}).values():
                    assert colblock['role'] == 'reader', "Type is not reader"
                    assert colblock['value']['alive'], "Block is not alive!"

                    if not (colblock['value']['type'] == 'page' and colblock['value']['parent_table'] == 'collection'):
                        continue

                    # Create the current collection:
                    root_collection_id = self.save_category(None, {
                        'title': colblock['value']['properties']['title'][0][0],
                    })

                    current_collection_id = root_collection_id
                    for element_id in colblock['value']['content']:
                        assert collection['block'][element_id]['role'] == 'reader', "Type is not reader"
                        current_element = collection['block'][element_id]['value']

                        assert current_element['alive'], "Block is not alive!"
                        if current_element['type'] == 'sub_sub_header':
                            # Sub category
                            current_collection_id = self.save_category(root_collection_id, {
                                'title': current_element['properties']['title'][0][0]
                            })
                        elif current_element['type'] == 'page':
                            page_id = current_element['id']  # bold!
                            page = self.retrieve(base_url[0:base_url.rfind('-')] + '-' + page_id.replace('-', ''))

                            assert page['block'][page_id]['role'] == 'reader', "Type is not reader"
                            assert page['block'][page_id]['value']['alive'], "Block is not alive!"

                            entry = {
                                'title': page['block'][page_id]['value']['properties']['title'][0][0],
                                'created': datetime.datetime.fromtimestamp(page['block'][page_id]['value']['created_time'] / 1000),
                                'last_updated': datetime.datetime.fromtimestamp(page['block'][page_id]['value']['last_edited_time'] / 1000)
                            }

                            entry['previous_url'] = '{}/{}-{}'.format(
                                base_url[0:base_url.find('/', 9)],
                                slugify(entry['title']),
                                page_id
                            )

                            content = ['<div>']
                            for block_id in page['block'][page_id]['value']['content']:
                                self.parse_block(page['block'], block_id, content)
                            content.append('</div>')

                            entry['content'] = ''.join(content)

                            self.save_article(current_collection_id or root_collection_id, entry)

    def _add_id(self, soup):
        if soup.attrs and soup.attrs.id:
            return

        soup.attrs['id'] = slugify(soup.get_text())

    def parse_block(self, blocks, block_id, content):
        try:
            assert blocks[block_id]['role'] == 'reader', "Type is not reader"
            assert blocks[block_id]['value']['alive'], "Block is not alive!"

            current = blocks[block_id]['value']

            properties = current.get('properties', {}).get('title', None)

            if current['type'] == 'text':
                content.append('<p>')
                if 'properties' in current:
                    self.parse_properties(properties, content)
                elif 'content' in current:
                    for sub_block_id in current['content']:
                        self.parse_block(blocks, sub_block_id, content)

                content.append('</p>')
            elif current['type'] == 'image':
                assert len(current['properties']['source']) == 1, "Unexpected size"
                assert len(current['properties']['source'][0]) == 1, "Unexpected size"
                assert len(current['properties']['title']) == 1, "Unexpected size"
                assert len(current['properties']['title'][0]) == 1, "Unexpected size"

                image_url = '{}/image/{}?table=block&id={}&spaceId={}&width={}&userId=&cache=v2'.format(
                    self.base_url,
                    urllib.parse.quote(current['properties']['source'][0][0], safe=''),
                    block_id,
                    current['space_id'],
                    current.get('format', {}).get('block_width', None) or 2000
                )

                content.append('<figure><img src="{0}" alt="{1}" /></figure>'.format(
                    image_url,
                    current['properties']['title'][0][0]
                ))
            elif current['type'] == 'numbered_list':
                if properties:
                    if current.get('format', {}).get('list_start_index'):
                        content.append('<ol start="{}">'.format(current['format']['list_start_index']))
                    else:
                        content.append('<ol>')

                    content.append('<li>')
                    self.parse_properties(properties, content)
                    content.append('</li>')
                    content.append('</ol>')
            elif current['type'] == 'bulleted_list':
                if properties:
                    content.append('<ul>')
                    content.append('<li>')
                    self.parse_properties(properties, content)
                    content.append('</li>')
                    content.append('</ul>')
            elif current['type'] == 'sub_header':
                if properties:
                    content.append('<h2>')
                    self.parse_properties(properties, content)
                    content.append('</h2>')
            elif current['type'] == 'sub_sub_header':
                if properties:
                    content.append('<h3>')
                    self.parse_properties(properties, content)
                    content.append('</h3>')
            elif current['type'] == 'callout':
                if properties:
                    assert current.get('format', {}).get('block_color') == 'gray_background'
                    content.append('<div class="callout callout--info">')
                    self.parse_properties(properties, content)
                    content.append('</div>')
            else:
                raise NotImplementedError("Unknown type: {}".format(current['type']))
        except Exception:
            print(json.dumps(blocks, indent=4))
            raise

    def _parse_url(self, url):
        if not url:
            return None

        if url.startswith('/'):
            return self.base_url + url

    def parse_properties(self, properties, content):
        try:
            for text in properties:
                wrappers = []
                output = ''
                if len(text) == 2:
                    for w in text[1]:
                        wrapper = w[0][0]
                        if wrapper == 'b':
                            assert len(w) == 1, "Unexpected size"
                            output += '<strong>'
                            wrappers.append('strong')
                        elif wrapper == 'i':
                            assert len(w) == 1, "Unexpected size"
                            output += '<em>'
                            wrappers.append('em')
                        elif wrapper == '_':
                            assert len(w) == 1, "Unexpected size"
                            output += '<U>'
                            wrappers.append('U')
                        elif wrapper == 'a':
                            assert len(w) == 2, "Unexpected size"

                            if w[1].startswith('/'):
                                output += '<a href="{}">'.format(self._parse_url(w[1]))
                            else:
                                output += '<a href="{}" rel="noopener noreferrer">'.format(self._parse_url(w[1]))

                            wrappers.append('a')
                        else:
                            raise NotImplementedError("Unknown wrapper: {}".format(wrapper))

                        wrappers.append(wrapper)

                output += text[0]
                for w in sorted(wrappers, reverse=True):
                    output += '</{0}>'.format(w)

                content.append(output)
        except NotImplementedError:
            print(json.dumps(properties, indent=4))
            raise
