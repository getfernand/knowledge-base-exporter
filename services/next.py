# -*- coding:utf-8 -*-

from .base import KnowledgeBaseImporter
from bs4 import BeautifulSoup
from slugify import slugify
import json

HEADING_MAPPER = {'heading': 'h2', 'subheading': 'h3', 'subheading3': 'h4', 'subheading4': 'h5'}


class Next(KnowledgeBaseImporter):
    def load(self, base_url: str, language=None):
        if not base_url.endswith('/'):
            base_url += '/'

        self.add_language(language or 'en', base_url)
        data = self.retrieve(self.base_url)

        metadata = {
            # knowledge_bases
            'custom_domain': data['props']['pageProps']['theme'].get('customDomain'),
            'favicon': data['props']['pageProps']['theme']['favicon'],
            'logo': data['props']['pageProps']['theme']['logo'],
            'accent_color': '#{}'.format(data['props']['pageProps']['theme']['color']),
            'code': data['props']['pageProps']['theme']['locale'].upper(),
            'title': data['props']['pageProps']['theme']['siteName'],
            'description': data['props']['pageProps']['theme']['headline'],
            'company_name': data['props']['pageProps']['app']['name'],
            'company_url': data['props']['pageProps']['theme'].get('homeUrl'),
            'links': []
        }

        highest_sort = 0
        for link in data['props']['pageProps']['helpCenterSite']['footerLinks']['custom']:
            metadata['links'].append({
                'title': link['title'],
                'url': link['url'],
                'sort': link['sort_order'],
                'position': 'footer'
            })

            if highest_sort < link['sort_order']:
                highest_sort = link['sort_order']

        if 'social' in data['props']['pageProps']['helpCenterSite']['footerLinks']:
            for link in data['props']['pageProps']['helpCenterSite']['footerLinks']['social']:
                highest_sort += 1

                metadata['links'].append({
                    'title': link['provider'].title(),
                    'url': link['url'],
                    'sort': highest_sort,
                    'position': 'footer'
                })

        for link in data['props']['pageProps']['helpCenterSite']['headerLinks']:
            metadata['links'].append({
                'title': link['title'],
                'url': link['url'],
                'sort': link['sort_order'],
                'position': 'header'
            })

        self.set_metadata(metadata)

        for item in data['props']['pageProps']['home']['collections']:
            self.get_collections(item, None)

    def retrieve(self, url):
        url = self.get_url(url)
        soup = super().retrieve(url)
        d = soup.find('script', {'id': '__NEXT_DATA__'})

        if not d:
            self.remove_cache(url)
            raise AssertionError('Could not find __NEXT_DATA__ script tag.')

        data = json.loads(d.string)
        if data['page'] == '/404':
            self.remove_cache(url)
            raise AssertionError('Page not found')

        return data

    def get_article(self, url, collection_id):
        slug = url[url.rfind('/') + 1:]
        slug = '-'.join(slug.split('-')[1:])

        data = self.retrieve(url)

        # Intercom does not have created/updated properties
        self.save_article(
            collection_id,
            {
                'title': data['props']['pageProps']['articleContent']['title'],
                'slug': slug,
                'previous_url': url[url.find('/', 10):],
                'description': data['props']['pageProps']['articleContent']['description'],
                'content': self.build_blocks(url, data['props']['pageProps']['articleContent']['blocks'])
            }
        )

    def get_collections(self, entry, parent_id=None):
        collection_id = self.save_category(parent_id, {
            'title': entry['name'],
            'slug': entry['slug'],
            'description': entry['description']
        })

        childs = self.retrieve(entry['url'])
        if len(childs['props']['pageProps']['collection'].get('articleSummaries', [])) > 0:
            for article in childs['props']['pageProps']['collection']['articleSummaries']:
                self.get_article(article['url'], collection_id)

        if len(childs['props']['pageProps']['collection'].get('subcollections', [])) > 0:
            subindex = 0
            for col in childs['props']['pageProps']['collection']['subcollections']:
                self.get_collections(col, collection_id)
                subindex += 1

    def clean_text(self, text):
        return text.replace('<b>', '<strong>').replace('</b>', '</strong>')

    def parse_block(self, block):
        content = ''
        classes = []
        if 'align' in block:
            classes.append('align--{}'.format(block['align']))

        if block['type'] == 'paragraph':
            assert block.get('class', 'no-margin') == 'no-margin', 'Unexpected class name!'
            assert len([x for x in block.keys() if x not in ('type', 'text', 'class', 'align')]) == 0, 'Unexpected property'

            if block['text'].strip() != '':
                if classes:
                    content = '<p class="{}">'.format(' '.join(classes))
                else:
                    content = '<p>'
                content += '{}</p>'.format(self.clean_text(block['text']))
        elif block['type'] == 'image':
            assert len([x for x in block.keys() if x not in ('type', 'url', 'width', 'height', 'displayWidth', 'text', 'align', 'linkUrl')]) == 0, 'Unexpected property'
            content = ''
            attributes = {}

            if 'linkUrl' in block:
                content = '<a href="{}" target="_blank" rel="noopener noreferrer">'.format(block['linkUrl'])

            if classes:
                content += '<figure class="{}">'.format(' '.join(classes))
            else:
                content += '<figure>'

            filename = block['url'][block['url'].rfind('/') + 1:]
            attributes['src'] = block['url']
            attributes['width'] = block.get('displayWidth') or block.get('width')
            attributes['height'] = block.get('height')
            attributes['alt'] = block.get('text') or filename

            content += '<img {}>'.format(' '.join(['{}="{}"'.format(k, attributes[k]) for k in attributes.keys() if attributes[k] is not None]))
            content += '</figure>'
            if 'linkUrl' in block:
                content += '</a>'
        elif block['type'] in ('heading', 'subheading', 'subheading3', 'subheading4'):
            assert len([x for x in block.keys() if x not in ('type', 'idAttribute', 'text', 'tag', 'align')]) == 0, 'Unexpected property'
            attributes = {}
            if classes:
                attributes['class'] = classes

            if block.get('idAttribute') and not block.get('idAttribute').startswith('h_'):
                attributes['id'] = block['idAttribute']

            if 'id' not in attributes:
                attributes['id'] = slugify(block['text'])

            return '<{tag} {attributes}>{text}</{tag}>'.format(**{
                'tag': HEADING_MAPPER[block['type']],
                'text': self.clean_text(block['text']),
                'attributes': ' '.join(['{}="{}"'.format(k, attributes[k]) for k in attributes.keys() if attributes[k] is not None])
            })
        elif block['type'] == 'button':
            assert block['buttonStyle'] == 'solid', 'Unexpected button style'
            assert len([x for x in block.keys() if x not in ('type', 'text', 'linkUrl', 'buttonStyle', 'align')]) == 0, 'Unexpected property'

            if classes:
                content = '<p class="{}">'.format(' '.join(classes))
            else:
                content = '<p>'

            content += '<a href="{linkUrl}" title="{text}" class="action" rel="noopener noreferrer">{text}</a></p>'.format(
                linkUrl=block['linkUrl'],
                text=self.clean_text(block['text'])
            )
        elif block['type'] in ('unorderedNestedList', 'orderedNestedList'):
            content += '<div><{}l>'.format(block['type'][0:1])
            for item in block['items']:
                content += '<li>'
                for itemContent in item['content']:
                    content += self.parse_block(itemContent)
                content += '</li>'

            content += '</{}l></div>'.format(block['type'][0:1])
        elif block['type'] == 'collapsibleSection':
            return '''<div class="collapsible">
                    <div class="collapsible__header">{summary}</div>
                    <div class="collapsible__content">{content}</div>
                </div>'''.format(
                summary=self.parse_block(block['summary']),
                content=''.join([self.parse_block(x) for x in block['content']])
            )
        elif block['type'] == 'horizontalRule':
            return '<hr>'
        elif block['type'] == 'code':
            return '<pre><code>{}</code></pre>'.format(block['text'].strip())
        elif block['type'] == 'video':
            assert block['provider'] == 'wistia'
            assert len([x for x in block.keys() if x not in ('type', 'provider', 'id')]) == 0, 'Unexpected property'
            return '<div class="iframe-wrapper video-embed"><iframe src="https://fast.wistia.net/emed/iframe/{}" frameborder="0" allowfullscreen="allowfullscreen" allow="fullscreen; picture-in-picture"></iframe></div>'.format(block['id'])
        elif block['type'] == 'callout':
            assert len([x for x in block.keys() if x not in ('type', 'content', 'style')]) == 0, 'Unexpected property'
            assert len(classes) == 0, 'Unknown classes {}'.format(classes)
            if block['style']['backgroundColor'] == '#e3e7fa80':  # blue
                state = ' callout--info'
            elif block['style']['backgroundColor'] == '#feedaf80':  # yellow
                state = ' callout--warning'
            elif block['style']['backgroundColor'] == '#fed9db80':  # red
                state = ' callout--danger'
            elif block['style']['backgroundColor'] == '#d7efdc80':  # green
                state = ' callout--success'
            elif block['style']['backgroundColor'] == '#e8e8e880':  # grey
                state = ' callout--info'
            else:
                raise AssertionError('Unknown color style {}'.format(block['style']))

            content += '<div class="callout{}">'.format(state)
            for sub in block['content']:
                content += self.parse_block(sub)
            content += '</div>'

        elif block['type'] == 'table':
            assert block['responsive'] is False
            assert block['container'] is False
            assert block['stacked'] is True
            content += '<table>'
            for row in block['rows']:
                content += '<tr>'
                for cell in row['cells']:
                    content += '<td>'
                    for sub in cell['content']:
                        content += self.parse_block(sub)
                    content += '</td>'
                content += '</tr>'
            content += '</table>'
        else:
            raise AssertionError('Unknown block type: {}'.format(block['type']))

        return content

    def build_blocks(self, url, blocks):
        content = '<div>'
        for block in blocks:
            try:
                content += self.parse_block(block)
            except AssertionError as e:
                print('')
                print(str(e))
                print('> for url: {}'.format(url))
                print(json.dumps(block, indent=4))
                print('')
        content += '</div>'

        soup = BeautifulSoup(content, features='html.parser')
        return str(soup)
