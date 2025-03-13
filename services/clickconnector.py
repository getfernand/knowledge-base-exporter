# -*- coding:utf-8 -*-
from .next import Next
from slugify import slugify
from bs4 import BeautifulSoup


# @see https://clickconnector.com/
class Clickconnector(Next):
    def load(self, base_url: str, language=None):
        if not base_url.endswith('/'):
            base_url += '/'

        self.add_language(language or 'en', base_url)
        data = self.retrieve(self.base_url)

        portal_data = data['props']['pageProps']['portalConfig']['data']

        metadata = {
            # knowledge_bases
            'title': portal_data['siteName'],
            'favicon': portal_data['seo']['favicon'],
            'description': portal_data['seo']['description'],
            'logo': portal_data['navBar']['logo'],
            'accent_color': portal_data['appearance']['primaryColor'],
            'code': language.upper(),
            'links': []
        }

        if portal_data.get('domain', {}).get('customDomainConfig', {}).get('isVerified'):
            metadata['custom_domain'] = portal_data['domain']['customDomainConfig']['domain']

        assert len(portal_data['navBar']['buttons']) == 0, "Unexpected section buttons. Not supported yet."

        highest_sort = 0
        for link in portal_data['navBar']['links']:
            metadata['links'].append({
                'title': link['title'],
                'url': link['url'],
                'sort': link['sort_order'],
                'position': 'header'
            })

            if highest_sort < link['sort_order']:
                highest_sort = link['sort_order']

        highest_sort = 0
        for link in portal_data['footer']['socialLinks']:
            metadata['links'].append({
                'title': link['title'],
                'url': link['url'],
                'sort': link['sort_order'],
                'position': 'footer'
            })

            if highest_sort < link['sort_order']:
                highest_sort = link['sort_order']

        for link in portal_data['footer']['linkSections']:
            metadata['links'].append({
                'title': link['title'],
                'url': link['url'],
                'sort': link['sort_order'],
                'position': 'footer'
            })

            if highest_sort < link['sort_order']:
                highest_sort = link['sort_order']

        self.set_metadata(metadata)

        collections = {}
        for item in data['props']['pageProps']['collections']:
            collections[item['id']] = item

        for id in data['props']['pageProps']['portalConfig']['data']['collections']['collectionOrder']:
            item = collections[id]
            self.get_collections(item, None)
            del collections[id]

        for id in list(collections.keys())[:]:
            item = collections[id]
            self.get_collections(item, None)
            del collections[id]

    def get_collections(self, entry, parent_id=None):
        slug = slugify(entry['label'])

        collection_id = self.save_category(parent_id, {
            'title': entry['label'],
            'slug': slug,
            'description': entry.get('description')
        })

        childs = self.retrieve(f'/collections/{slug}-{entry["id"]}')
        if len(childs['props']['pageProps'].get('articles', [])) > 0:
            for article in childs['props']['pageProps']['articles']:
                self.get_article(article, collection_id)

        if len(childs['props']['pageProps']['collection'].get('subcollections', [])) > 0:
            subindex = 0
            for col in childs['props']['pageProps']['collection']['subcollections']:
                self.get_collections(col, collection_id)
                subindex += 1

    def get_article(self, article, collection_id):
        slug = slugify(article['title'])
        url = '/articles/' + slug + '-' + article['id']
        data = self.retrieve(url)
        article = data['props']['pageProps']['article']
        final_url = self.get_url(url)

        # Intercom does not have created/updated properties
        self.save_article(
            collection_id,
            {
                'title': article['title'],
                'description': article.get('description'),
                'created': article.get('metaData', {}).get('createdAt'),
                'last_updated': article.get('metaData', {}).get('updatedAt'),
                'slug': slug,
                'previous_url': final_url,
                'content': self.parse_content(final_url, article['body'])
            }
        )

    def parse_content(self, url, content):
        soup = BeautifulSoup(content, features='html.parser')
        CLASSES = (
            'PlaygroundEditorTheme__textBold', 'PlaygroundEditorTheme__paragraph', 'PlaygroundEditorTheme__ul', 'PlaygroundEditorTheme__ol1',
            'PlaygroundEditorTheme__listItem', 'PlaygroundEditorTheme__link', 'PlaygroundEditorTheme__textItalic', 'PlaygroundEditorTheme__nestedListItem',
            'PlaygroundEditorTheme__h1', 'PlaygroundEditorTheme__h2', 'PlaygroundEditorTheme__h3', 'PlaygroundEditorTheme__h4',
            'PlaygroundEditorTheme__textItalic', 'PlaygroundEditorTheme__textUnderline', 'PlaygroundEditorTheme__table', 'PlaygroundEditorTheme__tableCell',
            'keyword'
        )
        for item in soup.find_all():
            if item.decomposed:
                continue

            if 'dir' in item.attrs:
                del item['dir']

            if item.name == 'pre':
                del item['class']
                # get content as text:
                # We replace all the "br" element by a "\n" string
                for br in item.find_all('br'):
                    br.replace_with('\n')

                raw_code = item.get_text()
                language = item.attrs['data-highlight-language']

                pre = soup.new_tag('pre')
                code = soup.new_tag('code')
                code.string = raw_code
                code.attrs['class'] = ['hljs', 'language-{}'.format(language)]
                pre.attrs['class'] = ['hljs']
                pre.append(code)
                item.insert_after(pre)
                item.decompose()
                continue
            elif item.name == 'a':
                if 'href' in item.attrs:
                    item.attrs['href'] = self.get_url(item.attrs['href'])

                # add nofollow noopener noreferrer
                item.attrs['rel'] = 'nofollow noopener noreferrer'
            elif item.name != 'code' and item.attrs.get('class', []).count('PlaygroundEditorTheme__textCode') > 0 and item.parent.name == 'code':
                item.unwrap()
                del item.attrs['class']
            elif item.name == 'li':
                if 'value' in item.attrs:
                    del item['value']
            elif item.name == 'span':
                try:
                    item.unwrap()
                except ValueError:
                    pass
            elif item.name == 'strong' and item.parent.name == 'b':
                item.parent.name = 'strong'
                item.unwrap()
            elif item.name == 'img':
                if item.attrs.get('height') == 'inherit':
                    del item['height']
                if item.attrs.get('width') == 'inherit':
                    del item['width']

                if item.parent.name != 'figure':
                    if item.parent.name == 'p':
                        item.parent.name = 'figure'
                    else:
                        # wrap the image in a figure tag
                        figure = soup.new_tag('figure')
                        item.wrap(figure)

                    item.parent.attrs['class'] = ['align--center width--normal']
            elif item.name == 'br' and item.parent and item.parent.name == 'p':
                # we only remove the item if the parent has only one child, which is the <br> tag
                if len(item.parent.contents) == 1:
                    item.parent.decompose()
                    continue

            if 'class' in item.attrs:
                if 'PlaygroundEditorTheme__textUnderline' in item.attrs['class']:
                    item.attrs['class'].remove('PlaygroundEditorTheme__textUnderline')
                    item.name = 'u'

                for x in CLASSES:
                    item.attrs['class'].remove(x) if x in item.attrs['class'] else None

                if len(item.attrs['class']) == 0:
                    del item['class']
                else:
                    if item.attrs['class'].count('hljs') > 0 and item.name in ('pre', 'code'):
                        continue

                    print('')
                    print(url)
                    print('')
                    print(str(soup))
                    raise Exception('Unexpected class: ' + str(item.attrs['class']))

        return str(soup)
