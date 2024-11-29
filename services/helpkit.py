# -*- coding:utf-8 -*-

from .nuxt import Nuxt
from bs4 import BeautifulSoup, Comment, NavigableString
from slugify import slugify
import datetime


class Helpkit(Nuxt):
    def get_long_uuid(self, short_uuid):
        alphabet = '123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'

        num = 0
        for s in short_uuid:
            num = num * 58 + alphabet.index(s)

        uuid = '{:06x}'.format(num)
        return '{}-{}-{}-{}-{}'.format(
            uuid[:8], uuid[8:12], uuid[12:16], uuid[16:20], uuid[20:]
        )

    def get_short_uuid(self, uuid):
        """Convert a given uuid to a short uuid following https://www.npmjs.com/package/short-uuid"""
        num = int(uuid.replace('-', ''), 16)
        alphabet = '123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
        result = []
        while num > 0:
            result = [alphabet[num % 58]] + result
            num  = num // 58
        return ''.join(result)

    def load(self, base_url: str, language=None):
        if base_url.endswith('/'):
            base_url = base_url[:-1]

        self.add_language('en', base_url)
        soup = self.retrieve(base_url)

        self.articles_mapping = {}
        articles = []

        for col in soup.select('#__layout .helpkit-category-card'):
            url = col.attrs['href']  # Should be of format /slug/short_uuid/
            slug, _ = url.split('/')[1:]  # This purposely to fail if the format is not as expected

            current_icon = None
            try:
                current_icon = col.select('.helpkit-category-icon-emoji')[0].text.strip()
            except IndexError:
                pass

            root_collection_id = self.save_category(None, {
                'icon': current_icon,
                'title': col.find('h2').text.strip(),
                'slug': slug,
                'description': col.select('.leading-snug')[0].text.strip(),
                'url': url
            })

            col_soup = self.retrieve(url)
            sub_collections = list(col_soup.select('#__layout .helpkit-subcollection-wrapper'))
            for entry in sub_collections:
                current_collection_id = root_collection_id

                if len(sub_collections) > 1:
                    # We only create a sub collection when it's interesting
                    current_collection_id = self.save_category(root_collection_id, {
                        'title': entry.find('h2').text.strip(),
                        'icon': current_icon
                    })

                index = 0
                for card in entry.select('.helpkit-article-card'):
                    url = card.attrs['href']
                    url_sections = url[1:].split('/')
                    short_uuid = url_sections.pop(-1)
                    slug = url_sections.pop(-1)

                    article = {
                        'uuid': self.get_long_uuid(short_uuid),
                        'short_uuid': short_uuid,
                        'title': card.find('h3').text.strip(),
                        'slug': slug,
                        'description': card.find('p').text.strip(),
                        'previous_url': card.attrs['href'],
                        'collection_id': current_collection_id,
                        'index': index
                    }
                    articles.append(article)
                    self.articles_mapping['/' + article['uuid'].replace('-', '')] = self.base_url + article['previous_url']
                    index += 1

        # Now we load the articles content:
        for article in articles:
            article_content = self.retrieve(article['previous_url'])
            try:
                last_update_str = article_content.select('.helpkit-article-meta-wrapper p')[0].text.replace('Last updated on', '').strip().lower()
                article['last_update'] = datetime.datetime.strptime(last_update_str, '%B %d, %Y')
            except IndexError:
                pass  # It can happen that there is no date!

            try:
                content = self.parse_content(article['previous_url'], article_content, article_content.select('#article-{} main'.format(article['short_uuid']))[0])
            except Exception as e:
                print('')
                print('Exception : {}'.format(str(e)))
                print('While processing {}'.format(self.base_url + url))
                raise

            output = str(content)
            assert output.find('"notion-') == -1

            self.save_article(
                article['collection_id'],
                {
                    'title': article['title'],
                    'slug': article['slug'],
                    'description': article['description'],
                    'previous_url': article['previous_url'],
                    'content': output
                }
            )

    def parse_content(self, url, soup, content):
        assert content.name == 'main'
        assert content.attrs.get('class', []) == ['notion']

        content.name = 'div'
        content.attrs.pop('class', None)

        for name in ('ul', 'ol'):
            for ul in content.find_all(name):
                if ul.name is None:
                    # it was decomposed, we ignore
                    continue

                if ul.attrs and str(ul.attrs.get('start')) == '1':
                    ul.attrs.pop('start', None)

                for sibling in list(ul.next_siblings):
                    if not sibling or sibling.name != ul.name:
                        break

                    if sibling and sibling.name == ul.name:
                        for li in sibling.find_all('li', recursive=False):
                            ul.append(li.extract())

                        sibling.extract()

                try:
                    ul.attrs.get('class').remove('notion-list')
                except ValueError:
                    raise AssertionError('notion-list not found in class')

                self._remove_class(ul, ul.attrs.get('class', []), ['notion-list-disc', 'notion-list-numbered'])

        # Cleaning tables
        for table in content.find_all('table'):
            headers = list(table.select('.notion-simple-table-header'))
            if len(headers) > 0:
                assert headers[0].parent.parent.name == 'tr'
                thead = soup.new_tag('thead')
                current_tr = headers[0].parent.parent.extract()
                for td in current_tr.find_all('td'):
                    td.name = 'th'
                thead.append(current_tr)
                table.insert(0, thead)

            footers = list(table.select('.notion-simple-table-footer'))
            if len(footers) > 0:
                assert footers[0].parent.parent.name == 'tr'
                tfoot = soup.new_tag('tfoot')
                current_tr = footers[0].parent.parent.extract()
                for td in current_tr.find_all('td'):
                    td.name = 'th'
                tfoot.append(current_tr)
                table.append(tfoot)

        # This is for debugging purpose only
        for k in content.find_all():
            if k.name is None or k.decomposed:
                continue

            if k.name in ('b', 'em', 'strong', 'u', 's', 'span', 'pre'):  # removing inlines
                childs = list(k.children)
                if len(childs) == 1 and childs[0].name == k.name:
                    k.unwrap()
                    continue

            if k.attrs:
                custom_attrs = list(k.attrs.keys())
                if 'fragment' in k.attrs:
                    custom_attrs.remove('fragment')
                    k.attrs.pop('fragment', None)
                if 'style' in k.attrs:
                    custom_attrs.remove('style')
                    k.attrs.pop('style', None)

                for attr in ('target', 'href', 'src', 'allow', 'class', 'rel', 'start', 'alt'):
                    if attr in custom_attrs:
                        custom_attrs.remove(attr)

                if custom_attrs:
                    print('Remaining attribute :', custom_attrs, k)

            if isinstance(k, NavigableString) and k.string == ' ':
                k.string = '&nbsp;'

            if k.name in ('ul', 'ol', 'li', 'b', 'strong', 'em', 'u', 's', 'thead', 'tbody', 'tfoot', 'th', 'tr', 'td', 'iframe'):
                if k.attrs:
                    k.attrs.pop('class', None)
                continue

            classlist = []
            if k.attrs and k.attrs.get('class'):
                classlist = k.attrs['class']

            try:
                if k.name == 'div':
                    if len(classlist) == 0:
                        k.unwrap()
                    elif classlist == ['notion-spacer'] or classlist == ['notion-sync-block']:
                        k.unwrap()
                    elif 'notion-blank' in classlist:
                        k.replace_with(BeautifulSoup('<p></p>', 'html.parser'))
                    elif 'notion-asset-wrapper' in classlist:
                        first_child = list(k.children)[0]
                        if first_child.name == 'iframe':
                            first_child['src'] = self._video_no_cookie(first_child['src'])
                            self._remove_class(k, classlist, 'notion-asset-wrapper')
                            k.attrs['class'] = 'iframe-wrapper video-embed'
                            self._remove_class(first_child, first_child.attrs.get('class', []) if first_child.attrs else [], ['notion-image-inset', 'notion-embed'])
                        else:
                            raise KeyError()
                    elif 'notion-callout' in classlist:
                        k.attrs['class'] = ['callout']
                        if len(k.select('.notion-page-icon')) > 0:
                            k.attrs['class'].append('callout--icon')

                        if 'notion-gray_background' in classlist:
                            k.attrs['class'].append('callout--info')
                        elif 'notion-orange_background':
                            k.attrs['class'].append('callout--warning')
                        else:
                            print('Unknown callout type : {}'.format(classlist))

                        for child in k.children:
                            if child.attrs and 'notion-callout-text' in child.attrs.get('class'):
                                child.attrs.pop('class', None)
                                child.name = 'p'
                                child.wrap(soup.new_tag('div'))
                                continue

                            child.decompose()

                    elif len(classlist) == 1 and classlist[0] in ('notion-row', 'notion-column', 'notion-simple-table-header', 'notion-simple-table-footer', 'notion-simple-table-wrapper', 'notion-simple-table-cell-text'):
                        k.unwrap()
                    else:
                        raise KeyError()
                elif k.name == 'span':
                    k.unwrap()
                elif k.name == 'pre':
                    # pre > code
                    if classlist:
                        k.attrs.pop('class', None)

                    # We clean what appears to be a shitty integration:
                    childs = list(k.children)
                    if childs[0].name == 'code':
                        for child in childs[0].children:
                            if child.name in ('pre', 'code'):
                                child.unwrap()
                    else:
                        if 'notion-code' in classlist:
                            classlist.remove('notion-code')

                        k.wrap(soup.new_tag('code', attrs={'class': classlist}))
                        # The cleaning will be done in the next section in that case
                elif k.name == 'code':
                    if 'notion-inline-code' in classlist:
                        # It's an inline ... should be
                        # addition: ... well it's not an inline ...

                        self._remove_class(k, classlist, 'notion-inline-code')
                        flatten = True
                        for child in k.children:
                            if child.name in ('pre', 'code'):
                                child.unwrap()
                            else:
                                # Contains other unknown tag
                                flatten = False

                        # We test that. It should be only one child but who knows ...
                        if flatten:
                            if child.string:
                                child.string = child.string.strip()
                            else:
                                child.string = ''.join(child.strings).strip()

                elif k.name == 'hr':
                    self._remove_class(k, classlist, 'notion-hr')
                elif k.name == 'h1':
                    self._remove_class(k, classlist, 'notion-h1')
                    k.name = 'h2'
                    self._add_id(k)
                elif k.name == 'h2':
                    self._remove_class(k, classlist, 'notion-h2')
                    self._add_id(k)
                elif k.name == 'h3':
                    self._remove_class(k, classlist, 'notion-h3')
                    self._add_id(k)
                elif k.name == 'h4':
                    self._remove_class(k, classlist, 'notion-h4')
                    self._add_id(k)
                elif k.name == 'h5':
                    self._remove_class(k, classlist, 'notion-h5')
                    self._add_id(k)
                elif k.name == 'h6':
                    self._remove_class(k, classlist, 'notion-h6')
                    self._add_id(k)
                elif k.name == 'p':
                    self._remove_class(k, classlist, 'notion-text')
                elif k.name == 'figure':
                    if 'notion-asset-wrapper' in classlist:
                        k.attrs.get('class').remove('notion-asset-wrapper')
                        if len(k.attrs.get('class', [])) == 0:
                            k.attrs.pop('class', None)
                elif k.name == 'figcaption':
                    self._remove_class(k, classlist, 'notion-image-caption')
                elif k.name == 'table':
                    self._remove_class(k, classlist, 'notion-simple-table')
                elif k.name == 'tr':
                    self._remove_class(k, classlist, 'notion-simple-table-row')
                elif k.name == 'td':
                    self._remove_class(k, classlist, 'notion-simple-table-data')
                elif k.name == 'blockquote':
                    self._remove_class(k, classlist, 'notion-quote')
                elif k.name == 'img':
                    self._remove_class(k, classlist, 'notion-image-inset')
                    if k.attrs and k.attrs.get('alt') == 'Notion image':
                        k.attrs.pop('alt', None)
                elif k.name == 'a':
                    if 'notion-bookmark' in classlist:
                        # It's a bootmark, we replace with another element
                        self._remove_class(k, classlist, 'notion-bookmark')

                        bookmark_url = self._extract_url(k.attrs['href'])
                        bookmark_title = k.select('.notion-bookmark-title')[0].text.strip()
                        try:
                            bookmark_description = k.select('.notion-bookmark-description')[0].text.strip()
                        except IndexError:
                            bookmark_description = None

                        try:
                            bookmark_image = k.select('.notion-bookmark-image img')[0].attrs['src']
                        except IndexError:
                            bookmark_image = None

                        for child in k.children:
                            if not isinstance(child, Comment):
                                child.decompose()
                            else:
                                child.extract()

                        k.attrs['url'] = bookmark_url
                        k.attrs['title'] = bookmark_title
                        k.attrs['target'] = '_blank'
                        k.attrs['rel'] = 'noopener noreferrer'

                        if bookmark_image:
                            k.append(BeautifulSoup(
                                '<figure><img src="{image_url}" title="{title}" /><figcaption>{description}</figcaption></figure>'.format(
                                    title=bookmark_title,
                                    description=bookmark_description or bookmark_title,
                                    image_url=bookmark_image
                                ),
                                'html.parser'
                            ))
                        else:
                            k.string = bookmark_description or bookmark_title

                    if 'notion-page-link' in classlist:
                        title = k.select('.notion-page-text')[0].text.strip()
                        for child in k.children:
                            child.decompose()

                        k.clear()
                        k.string = title
                    self._remove_class(k, classlist, ['notion-link', 'notion-page-link'])
                    k.attrs['rel'] = 'noopener noreferrer'
                    k.attrs['href'] = self._extract_url(k.attrs['href'])
                else:
                    raise KeyError()
            except KeyError as e:
                print('Unknown element')
                print(self.base_url + url)
                print(k)
                print(k.name, k.attrs)
                print('')
                raise
            except AssertionError as e:
                print('ASSERTION ERROR: {}'.format(str(e)))
                print(self.base_url + url)
                print(k.name, k.attrs, k)
                print('')
                raise

        for comment in content.find_all(text=True):
            if isinstance(comment, Comment):
                comment.extract()

        for paragraph in content.find_all('p'):
            # Remove the paragraph if it is empty:
            if len(paragraph.contents) == 0:
                paragraph.extract()

        return content

    def _remove_class(self, soup, classlist, name, empty=True):
        if len(classlist) == 0:
            return

        if isinstance(name, str):
            name = [name]

        for k in name:
            if k in classlist:
                classlist.remove(k)

        if empty:
            assert len(classlist) == 0, "Remaining unknown classes: {}".format(classlist)
            soup.attrs.pop('class', None)

    def _extract_url(self, url):
        if not url.startswith('/'):
            return url

        if url in self.articles_mapping:
            return self.articles_mapping.get(url, url)
        elif len(url) == 33 and url[1:].isalnum():
            # It's a UUID mapping that doesn't exists anymore, we replace with a hashtag
            return '#'

        print('URL NOT FOUND: {}'.format(url))
        return url

    def _add_id(self, soup):
        if soup.attrs and soup.attrs.id:
            return

        soup.attrs['id'] = slugify(soup.get_text())
