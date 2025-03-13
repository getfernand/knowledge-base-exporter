# -*- coding:utf-8 -*-
from .base import KnowledgeBaseImporter
from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup, NavigableString
import datetime, base64, os


class Gitbook(KnowledgeBaseImporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        try:
            playwright = sync_playwright().start()
            self.browser = playwright.chromium.connect_over_cdp('http://localhost:9222')
        except Exception:
            print('You must start a Chromium instance by calling')
            print('google-chrome --headless --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-profile')
            exit()

    def load(self, base_url: str, language=None):
        if not base_url.endswith('/'):
            base_url += '/'

        if base_url[-4:].startswith('/') and base_url[-4:].endswith('/'):
            base_url = base_url[0:-4]

        self.process_language(language or 'en', base_url)

    def retrieve(self, url, return_url=False):
        url = self.get_url(url)
        new_url, html_content = self.get_cached_version(url)
        if not html_content:
            if len(self.browser.contexts) == 0:
                self.browser.new_context()

            if len(self.browser.contexts[0].pages) == 0:
                page = self.browser.contexts[0].new_page()

            page = self.browser.contexts[0].pages[0]
            for i in range(0, 3):
                try:
                    page.goto(url, wait_until='networkidle', timeout=60000)
                    break
                except TimeoutError:
                    if i == 2:
                        raise
                    continue

            html_content = page.content()
            new_url = page.url
            new_url, html_content = self.cache_request(url, new_url, html_content)

        soup = BeautifulSoup(html_content, features='html.parser')
        if return_url:
            return new_url, soup

        return soup

    def process_language(self, language, url, soup=None):
        self.add_language(language, url)

        if not soup:
            soup = self.retrieve(url)

        header = soup.select_one('body>header div.scroll-nojump>div')
        it = header.children

        # Header
        metadata = {}

        title = next(it).select_one('a')
        images = {}
        logo = title.select_one('img')
        if logo:
            if logo.attrs.get('srcset'):
                for imgset in logo.attrs['srcset'].split(','):
                    imgset = imgset.strip()
                    img_src, img_width = imgset.split(' ')
                    images[int(img_width.replace('w', ''))] = img_src

                # Order the images object by key:
                images = [v for k, v in sorted(images.items(), key=lambda item: item[0], reverse=True)]

                if len(images) > 0:
                    metadata['logo'] = images[0]
            else:
                metadata['logo'] = logo.attrs['src']

        title_text = title.select_one('div')
        if title_text:
            metadata['title'] = title_text.get_text()

        if not metadata.get('title'):
            metadata['title'] = soup.title.string

        self.set_metadata(metadata)

        # Header links
        menu = next(it)
        for link in list(menu.children)[1].find_all('a'):
            self.add_header_link(link.get_text(), link.attrs['href'])

        articles = self.add_submenu(None, soup.select_one('body>div aside>div>div>ul'))

        for article_url in articles:
            article = {}
            article['previous_url'], article_soup = self.retrieve(article_url, return_url=True)

            article_main = article_soup.select_one('div>main')

            childs = list(article_main.children)
            if len(childs) == 3:
                print('NO CONTENT FOR', article_url)
                continue

            assert len(childs) == 4

            article['title'] = childs[0].select_one('h1').get_text()
            description = childs[0].select_one('p')
            if description:
                article['description'] = description.get_text()

            try:
                article['content'] = self.parse_content(childs[1], article_soup)
            except Exception:
                print('Error for {}'.format(article['previous_url']))
                raise
            article['last_updated'] = datetime.datetime.fromisoformat(childs[3].select_one('p>time').attrs['datetime']).isoformat()

            self.save_article(articles[article_url], article)

    def add_submenu(self, category, menu):
        articles = {}
        for item in menu.find_all('li', recursive=False):
            """
            Items are either
                * a
                * div, ul
                * a, div>ul
            """
            childs = list(item.children)

            if len(childs) == 1:
                # Direct article
                assert childs[0].name == 'a'

                url = childs[0].attrs['href']
                if url.startswith('/'):
                    assert url not in articles
                    articles[url] = category
                else:
                    self.add_footer_link(childs[0].get_text(), url)

                continue

            assert len(childs) == 2
            # Collection

            # First child, either a or div, is the title of the category
            title_child = childs[0]
            root_category = self.save_category(category, {
                'title': title_child.get_text()
            })

            submenu = childs[1]
            if submenu.name == 'div':
                descendants = list(submenu.children)
                assert len(descendants) == 1
                submenu = descendants[0]

            assert submenu.name == 'ul'
            articles = articles | self.add_submenu(root_category, submenu)

        return articles

    def parse_content(self, content, soup):
        if 'class' in content.attrs:
            del content.attrs['class']

        for item in content.find_all():
            if item.decomposed:
                continue

            if item.name == 'template':
                item.extract()
                continue

            if item.name == 'div' and 'scalar-app' in (item.attrs.get('class', []) or []):
                for i in list(item.descendants)[::]:
                    if i and not isinstance(i, NavigableString):
                        i.decompose()
                item.decompose()
                continue

            if item.attrs.get('role') == 'table':
                item.name = 'table'
            elif item.attrs.get('role') == 'row':
                item.name = 'tr'
            elif item.attrs.get('role') == 'columnheader':
                item.name = 'th'
            elif item.attrs.get('role') == 'cell':
                item.name = 'td'
            elif item.attrs.get('role') == 'rowgroup':
                item.unwrap()
                continue
            elif item.attrs.get('role') in ('dialog', 'tablist', 'tab', 'tabpanel'):
                continue
            elif item.attrs.get('role'):
                print('-' * 80)
                print(item)
                print('unknown role', item.attrs['role'])

            for k in ('aria-busy', 'aria-label', 'aria-labelledby', 'aria-modal', 'role', 'style', 'tabindex', 'teleport', 'type', 'aria-hidden', 'aria-expanded'):
                if k in item.attrs:
                    del item.attrs[k]

            for k in list(item.attrs)[::]:
                if k.startswith('data-'):
                    del item.attrs[k]

            if item.name in ('p', 'ul', 'strong', 'i', 'ol', 'li', 'span', 'hr', 'figcaption', 'blockquote', 'code', 'table', 'tr', 'td', 'th', 'pre'):
                if 'class' in item.attrs:
                    del item.attrs['class']
                if 'title' in item.attrs:
                    del item.attrs['title']
            elif item.name in ('h2', 'h3', 'h4', 'h5', 'h6'):
                if 'class' in item.attrs:
                    del item.attrs['class']

                childs = list(item.children)
                if len(childs) == 2 and childs[0].select_one('a') is not None:
                    childs[0].decompose()
                    childs[1].unwrap()

            elif item.name == 'a':
                del item.attrs['class']
                item['target'] = '_blank'
                item['rel'] = 'noopener noreferrer'
                item['href'] = self.get_url(item['href'])
            elif item.name in ('svg', 'select', 'button'):
                for i in list(item.descendants)[::]:
                    if i and not isinstance(i, NavigableString):
                        i.decompose()
                item.decompose()
                continue
            elif item.name == 'picture':
                if item.select_one('img') is None:
                    figcaption = item.select_one('figcaption')
                    if figcaption:
                        figcaption.name = 'div'

                    item.unwrap()
                else:
                    item.name = 'figure'
                    childs = list(item.children)
                    if childs[0].name == 'div':
                        childs[0].unwrap()

            elif item.name == 'img':
                self.wrap_image_figure(item, soup)
            elif item.name == 'iframe':
                self.clean_iframe(item)
            elif item.name == 'div' and 'hint' in item.get('class', []):
                classes = ['callout']
                if ''.join(item.attrs['class']).find('bg-orange') > -1:
                    classes.append('callout--warning')

                childs = list(item.children)
                if len(childs) == 2:
                    # Has icon
                    classes.append('callout--icon')

                    if ' '.join(childs[0].attrs['class']).find('text-info') > -1:
                        classes.append('callout--info')
                    elif ' '.join(childs[0].attrs['class']).find('text-warning') > -1:
                        classes.append('callout--warning')
                    elif ' '.join(childs[0].attrs['class']).find('text-danger') > -1:
                        classes.append('callout--danger')
                    else:
                        print(' '.join(childs[0].attrs['class']))
                        raise AssertionError('Not found class')

                    childs[0].decompose()
                    # remove the index 0 from the childs array
                    del childs[0]

                subchilds = list(childs[0].children)
                if subchilds[0].name == 'svg':
                    classes.append('callout--icon')
                    subchilds[0].unwrap()

                childs[0].unwrap()
                item.attrs['class'] = classes

                childs = list(item.children)
                if childs[0].name == 'p':
                    childs[0].name = 'div'

            elif item.name == 'div':
                if 'class' in item.attrs:
                    del item.attrs['class']

                if 'title' in item.attrs:
                    del item.attrs['title']
            else:
                raise AssertionError('Unexpected item {}'.format(item.name))

            keys = list(item.attrs.keys())
            for k in ('class', 'id', 'target', 'href', 'rel', 'alt', 'src', 'allowfullscreen', 'allow', 'scrolling', 'frameborder'):
                if k in keys:
                    keys.remove(k)

            if len(keys) > 0:
                print(item)
                raise AssertionError('Keys unexpected {}'.format(', '.join(keys)))

        for div in content.find_all('div'):
            childs = list(div.children)
            if len(childs) == 1 and childs[0].name == 'div' and 'callout' not in (div.attrs.get('class', []) or []):
                div.unwrap()

        return str(content)
