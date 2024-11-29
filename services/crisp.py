# -*- coding:utf-8 -*-
from .base import KnowledgeBaseImporter
import datetime


class Crisp(KnowledgeBaseImporter):
    def __init__(self, *args, **kwargs):
        self.articles_map = {}
        super().__init__(*args, **kwargs)

    def load(self, base_url: str, language=None):
        if not base_url.endswith('/'):
            base_url += '/'

        if base_url[-4:].startswith('/') and base_url[-4:].endswith('/'):
            base_url = base_url[0:-4]

        url, soup = self.retrieve(base_url, return_url=True)
        for alternate in soup.select('head>link[rel="alternate"]'):
            if language and language.upper() != alternate.attrs['hreflang'].upper():
                continue
            self.process_language(alternate.attrs['hreflang'], alternate.attrs['href'], soup if alternate.attrs['href'] == url else None)

    def process_language(self, language, url, soup=None):
        self.add_language(language, url)

        if not soup:
            soup = self.retrieve(url)

        self.set_metadata({
            'title': soup.title.string,
            'icon': soup.select_one('link[rel="icon"]').attrs['href'],
            'logo': soup.select_one('a.csh-header-main-logo>img').attrs['src']
        })

        for category in soup.select('#body section[data-type="categories"] .csh-home-list>li'):
            category_url = self.get_url(category.select_one('.csh-box-link').attrs['href'])
            root_category = self.save_category(None, {
                'title': category.select_one('.csh-category-badge').string,
                'url': category_url,
                'description': category.select_one('.csh-home-list-label').string
            })

            col_soup = self.retrieve(category_url)

            for section in col_soup.select('#body div.csh-category>section .csh-category-section'):
                current_category = root_category
                articles = section.select('ul.csh-category-section-list>li')
                if len(articles) > 1:
                    sub_title = section.select_one('h6.csh-category-section-title')
                    if sub_title:
                        current_category = self.save_category(root_category, {
                            'title': sub_title.string
                        })

                for article in articles:
                    article_url = article.select_one('a.csh-box-link').attrs['href']
                    # Article ID is the last parameter of the url, which is a n-based alphanumerical value
                    article_id = article_url.strip('/').split('/')[-1].split('-')[-1]
                    assert article_id.isalnum(), "Invalid article id {}".format(article_id)

                    if article_id in self.articles_map:
                        self.add_article_to_category(self.articles_map[article_id], current_category)
                        continue

                    article_url, article_soup = self.retrieve(article_url, return_url=True)

                    main = article_soup.select_one('.csh-article-content article ')
                    updated = main.select_one('p.csh-article-content-updated').string.split(' ')[-1]
                    updated_dt = datetime.datetime.strptime(updated, '%d/%m/%Y')
                    self.articles_map[article_id] = self.save_article(current_category, {
                        'title': main.select_one('h1').string,
                        'previous_url': article_url,
                        'description': article_soup.select_one('meta[name="description"]').get('content'),
                        'content': self.parse_content(main.select_one('.csh-article-content-text'), article_soup),
                        'last_updated': updated_dt.isoformat()
                    })

    def parse_content(self, article, soup):
        article.select_one('.csh-article-content-separate-top').decompose()
        article.select_one('.csh-article-content-updated').decompose()
        article.select_one('.csh-article-content-separate-bottom').decompose()
        del article['class']
        del article['role']

        found = False
        for item in article.find_all():
            classes = item.get('class', [])

            if 'style' in item.attrs:
                del item['style']
            if 'onclick' in item.attrs:
                del item['onclick']

            if item.name == 'img':
                del item['loading']  # Or should we ?
                if not item.get('alt'):
                    del item['alt']

                if item.parent.name in ('p', 'div', 'span') and not item.parent.text.strip():
                    item.parent.unwrap()

                if item.parent.name != 'figure':
                    item.wrap(soup.new_tag('figure'))

                item.parent['class'] = ['align--center width--normal']
            elif item.name == 'br':
                del item['class']
            elif item.name == 'a':
                if item.get('class'):
                    del item['class']

                del item['role']
                item['target'] = '_blank'
                item['rel'] = 'noopener noreferrer'
            elif item.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                del item['class']
                del item['data-type']
                item.name = 'h{}'.format(str(int(item.name[1:]) + 1))  # We consider h1 as being the main article title
            elif item.name in ('table', 'thead', 'tr', 'td', 'th'):
                del item['class']
            elif 'csh-markdown-video' in classes:
                item.unwrap()
            elif 'csh-markdown-video-wrap' in classes:
                item.name = 'div'
                del item['class']
                iframe = next(item.children, None)
                assert iframe.name == 'iframe'
                iframe['src'] = self._video_no_cookie(iframe['src'])
                iframe['allowfullscreen'] = 'allowfullscreen'
                iframe['allow'] = 'fullscreen; picture-in-picture'
                iframe['frameborder'] = '0'
                iframe.parent['class'] = 'video-embed'
                if 'height' in iframe.attrs:
                    del iframe.attrs['height']
                if 'width' in iframe.attrs:
                    del iframe.attrs['width']
                if 'loading' in iframe.attrs:
                    del iframe.attrs['loading']
                if 'type' in iframe.attrs:
                    del iframe.attrs['type']

            elif 'csh-markdown-emphasis' in classes:
                item.name = 'div'
                classes = ['callout']
                if item['data-type'] == '|':
                    classes.append('callout--success')
                elif item['data-type'] == '||':
                    classes.append('callout--info')
                elif item['data-type'] == '|||':
                    classes.append('callout--warning')
                else:
                    raise AssertionError('Unknown data-type "{}" for callout'.format(item['data-type']))

                del item['data-type']
                item.wrap(soup.new_tag('div', attrs={'class': classes}))
            elif 'csh-markdown-image' in classes:
                continue  # Will be processed on the children's img tag
            elif 'csh-markdown-bold' in classes:
                item.name = 'strong'
                del item['class']
            elif 'csh-markdown-italic' in classes:
                item.name = 'i'
                del item['class']
            elif 'csh-markdown-underline' in classes:
                item.name = 'u'
                del item['class']
            elif 'csh-markdown-delete' in classes:
                item.name = 's'
                del item['class']
            elif 'csh-markdown-color' in classes:
                # <span class="csh-markdown csh-markdown-color" style="color: #2d3db4;">
                del item['class']
                item.name = 'div'
                item.wrap(soup.new_tag('div', attrs={'class': ['callout', 'callout--info']}))
            elif 'csh-markdown-list' in classes:
                # <span class="csh-markdown csh-markdown-list" data-type="*">
                data_type = item['data-type']
                try:
                    int(data_type)
                except ValueError:
                    assert item['data-type'] == '*', 'Unexpected data-type: "{}"'.format(item['data-type'])

                item.name = 'li'
                del item['class']
                tag_name = 'ul' if item['data-type'] == '*' else 'ol'
                del item['data-type']

                if (item.previous_sibling and item.previous_sibling.name in ('ul', 'ol')) or (item.previous_sibling and item.previous_sibling.previous_sibling and item.previous_sibling.previous_sibling.name in ('ul', 'ol')):
                    if item.previous_sibling.name == 'br':
                        item.previous_sibling.decompose()

                    item.previous_sibling.append(item)
                else:
                    item.wrap(soup.new_tag(tag_name))
            elif 'csh-markdown-line' in classes:
                item.name = 'br'
                del item['class']
            elif 'csh-markdown-code-clipboard' in classes:
                item.decompose()
            elif item.name == 'pre':
                del item['class']
                del item['data-copied']
            elif item.name == 'code':
                # For code, we consider it ok
                continue
            elif 'csh-markdown-code-inline' in classes:
                item.name = 'code'
                del item['class']
            elif 'csh-markdown-blockquote' in classes:
                item.name = 'blockquote'
                del item['class']
            elif 'csh-smiley' in classes:
                # What to do here !
                del item['class']
                continue
                if item['data-name'] == 'angry':
                    pass
                """
                .csh-smiley[data-name=angry] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PHBhdGggZD0iTTQxLjYgNTAuODhjLTYuMTg3LTUuMTItMTMuMDEzLTUuMTItMTkuMiAwLS43NDcuNjQtMS4zODctLjQyNy0uODUzLTEuMzg3QzIzLjQ2NyA0NS44NjcgMjcuMiA0Mi41NiAzMiA0Mi41NnM4LjY0IDMuMzA3IDEwLjQ1MyA2LjkzM2MuNTM0Ljg1NC0uMTA2IDEuOTItLjg1MyAxLjM4NyIgZmlsbD0iIzY2NGUyNyIvPjxwYXRoIGQ9Ik04Ljc0NyAyNC40MjdjLTEuNiA1LjAxMy42NCAxMC42NjYgNS42NTMgMTIuOTA2IDQuOTA3IDIuMzQ3IDEwLjY2Ny41MzQgMTMuNTQ3LTMuOTQ2bC03LjM2LTguMjE0eiIgZmlsbD0iI2ZmZiIvPjxnIGZpbGw9IiM2NjRlMjciPjxwYXRoIGQ9Ik0xMy4wMTMgMjUuMzg3QzExLjUyIDI4LjQ4IDEyLjkwNyAzMi4yMTMgMTYgMzMuNmMzLjA5MyAxLjQ5MyA2LjgyNy4xMDcgOC4yMTMtMi45ODcgMS4wNjctMi4wMjYtMTAuMjQtNy4yNTMtMTEuMi01LjIyNiIvPjxwYXRoIGQ9Ik04Ljc0NyAyNC40MjdjMS43MDYtMS4wNjcgMy43MzMtMS42IDUuNzYtMS42IDIuMDI2IDAgNC4wNTMuNTMzIDUuOTczIDEuMzg2IDEuODEzLjg1NCAzLjUyIDIuMTM0IDQuOTA3IDMuNjI3IDEuMjggMS42IDIuMzQ2IDMuNDEzIDIuNTYgNS40NGEzMy40NTQgMzMuNDU0IDAgMCAwLTQuMjY3LTMuNjI3Yy0xLjQ5My0xLjA2Ni0yLjk4Ny0xLjkyLTQuNDgtMi41Ni0xLjYtLjc0Ni0zLjItMS4yOC00LjkwNy0xLjgxMy0xLjkyLS4zMi0zLjYyNi0uNjQtNS41NDYtLjg1MyIvPjwvZz48cGF0aCBkPSJNNTUuMjUzIDI0LjQyN2MxLjYgNS4wMTMtLjY0IDEwLjY2Ni01LjY1MyAxMi45MDYtNC45MDcgMi4zNDctMTAuNjY3LjUzNC0xMy41NDctMy45NDZsNy4zNi04LjIxNHoiIGZpbGw9IiNmZmYiLz48ZyBmaWxsPSIjNjY0ZTI3Ij48cGF0aCBkPSJNNTAuOTg3IDI1LjM4N2MxLjQ5MyAzLjA5My4xMDYgNi44MjYtMi45ODcgOC4yMTMtMy4wOTMgMS40OTMtNi44MjcuMTA3LTguMjEzLTIuOTg3LTEuMDY3LTIuMDI2IDEwLjI0LTcuMjUzIDExLjItNS4yMjYiLz48cGF0aCBkPSJNNTUuMjUzIDI0LjQyN2MtMS43MDYtMS4wNjctMy43MzMtMS42LTUuNzYtMS42LTIuMDI2IDAtNC4wNTMuNTMzLTUuOTczIDEuMzg2LTEuODEzLjg1NC0zLjUyIDIuMTM0LTQuOTA3IDMuNjI3LTEuMjggMS42LTIuMzQ2IDMuNDEzLTIuNTYgNS40NGEzMy40NTQgMzMuNDU0IDAgMCAxIDQuMjY3LTMuNjI3YzEuNDkzLTEuMDY2IDIuOTg3LTEuOTIgNC40OC0yLjU2IDEuNi0uNzQ2IDMuMi0xLjI4IDQuOTA3LTEuODEzIDEuOTItLjMyIDMuNjI2LS42NCA1LjU0Ni0uODUzIi8+PC9nPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=blushing] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGcgZmlsbD0iI2ZmNzE3ZiIgb3BhY2l0eT0iLjgiPjxjaXJjbGUgY3g9IjUyLjA1MyIgY3k9IjM2LjI2NyIgcj0iOC41MzMiLz48Y2lyY2xlIGN4PSIxMS45NDciIGN5PSIzNi4yNjciIHI9IjguNTMzIi8+PC9nPjxnIGZpbGw9IiM2NjRlMjciPjxwYXRoIGQ9Ik00NS40NCA0MC44NTNjLTguNjQgNi4wOC0xOC4yNCA1Ljk3NC0yNi44OCAwLTEuMDY3LS43NDYtMS45Mi41MzQtMS4yOCAxLjcwNyAyLjY2NyA0LjI2NyA3Ljg5MyA4LjIxMyAxNC43MiA4LjIxMyA2LjgyNyAwIDEyLjA1My0zLjg0IDE0LjcyLTguMjEzLjY0LTEuMTczLS4yMTMtMi40NTMtMS4yOC0xLjcwN00yOC4yNjcgMjYuNTZjLTIuMDI3LTUuNDQtNS4wMTQtOC4yMTMtOC04LjIxMy0yLjk4NyAwLTUuOTc0IDIuNzczLTggOC4yMTMtLjIxNC41MzMuODUzIDEuNDkzIDEuMzg2Ljk2IDEuOTItMi4wMjcgNC4yNjctMi44OCA2LjYxNC0yLjg4IDIuMzQ2IDAgNC42OTMuODUzIDYuNjEzIDIuODguNjQuNTMzIDEuNi0uNDI3IDEuMzg3LS45Nk01MS42MjcgMjYuNTZjLTIuMDI3LTUuNDQtNS4wMTQtOC4yMTMtOC04LjIxMy0yLjk4NyAwLTUuOTc0IDIuNzczLTggOC4yMTMtLjIxNC41MzMuODUzIDEuNDkzIDEuMzg2Ljk2IDEuOTItMi4wMjcgNC4yNjctMi44OCA2LjYxNC0yLjg4IDIuMzQ2IDAgNC42OTMuODUzIDYuNjEzIDIuODguNTMzLjUzMyAxLjYtLjQyNyAxLjM4Ny0uOTYiLz48L2c+PC9nPjwvc3ZnPg==)
                }

                .csh-smiley[data-name=confused] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGcgZmlsbD0iIzY2NGUyNyI+PHBhdGggZD0iTTI1LjA2NyAyNi41NmMtMi4wMjctNS40NC01LjAxNC04LjIxMy04LTguMjEzLTIuOTg3IDAtNS45NzQgMi43NzMtOCA4LjIxMy0uMjE0LjUzMy44NTMgMS40OTMgMS4zODYuOTYgMS45Mi0yLjAyNyA0LjI2Ny0yLjg4IDYuNjE0LTIuODggMi4zNDYgMCA0LjY5My44NTMgNi42MTMgMi44OC42NC41MzMgMS42LS40MjcgMS4zODctLjk2TTQ4LjQyNyAyNi41NmMtMi4wMjctNS40NC01LjAxNC04LjIxMy04LTguMjEzLTIuOTg3IDAtNS45NzQgMi43NzMtOCA4LjIxMy0uMjE0LjUzMy44NTMgMS40OTMgMS4zODYuOTYgMS45Mi0yLjAyNyA0LjI2Ny0yLjg4IDYuNjE0LTIuODggMi4zNDYgMCA0LjY5My44NTMgNi42MTMgMi44OC41MzMuNTMzIDEuNi0uNDI3IDEuMzg3LS45Nk00Ni45MzMgMzguNGMwLS44NTMtLjUzMy0xLjkyLTEuOTItMi4yNC0zLjczMy0uNzQ3LTkuMTczLTEuMzg3LTE2LjIxMy0xLjM4N3MtMTIuNDguNzQ3LTE2LjIxMyAxLjM4N2MtMS4zODcuMzItMS45MiAxLjM4Ny0xLjkyIDIuMjQgMCA3Ljc4NyA1Ljk3MyAxNS41NzMgMTguMTMzIDE1LjU3M1M0Ni45MzMgNDYuMTg3IDQ2LjkzMyAzOC40Ii8+PC9nPjxwYXRoIGQ9Ik00Mi4zNDcgMzguNzJDNDAgMzguMjkzIDM1LjA5MyAzNy42NTMgMjguOCAzNy42NTNzLTExLjIuNjQtMTMuNTQ3IDEuMDY3Yy0xLjM4Ni4yMTMtMS40OTMuNzQ3LTEuMzg2IDEuNi4xMDYuNDI3LjEwNiAxLjA2Ny4zMiAxLjcwNy4xMDYuNjQuMzIuOTYgMS4zODYuODUzIDIuMDI3LS4yMTMgMjQuNTM0LS4yMTMgMjYuNTYgMCAxLjA2Ny4xMDcgMS4xNzQtLjIxMyAxLjM4Ny0uODUzLjEwNy0uNjQuMjEzLTEuMTc0LjMyLTEuNzA3IDAtLjg1My0uMTA3LTEuMzg3LTEuNDkzLTEuNiIgZmlsbD0iI2ZmZiIvPjxwYXRoIGQ9Ik02MS44NjcgMzAuMDhjMCA3LjY4LTEwLjM0NyA3LjY4LTEwLjM0NyAwIDAtNS41NDcgNS4yMjctMTEuMDkzIDUuMjI3LTExLjA5M3M1LjEyIDUuNTQ2IDUuMTIgMTEuMDkzeiIgZmlsbD0iIzY1YjFlZiIvPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=cool] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxwYXRoIGQ9Ik0zMiAwYzE3LjcwNyAwIDMyIDE0LjI5MyAzMiAzMlM0OS43MDcgNjQgMzIgNjQgMCA0OS43MDcgMCAzMiAxNC4yOTMgMCAzMiAwIiBmaWxsPSIjZmZkZDY3Ii8+PHBhdGggZD0iTTM2LjA1MyAxOS43MzNjLTIuMzQ2IDEuMTc0LTUuODY2IDEuMTc0LTguMjEzIDAtMi40NTMtMS4yOC01LjU0Ny0yLjEzMy05LjI4LTIuNDUzLTMuNjI3LS4zMi0xMS4yLS4zMi0xNC45MzMgMS4wNjctLjQyNy4xMDYtLjg1NC4zMi0xLjI4LjUzMy0uMTA3LjEwNy0uMjE0LjIxMy0uMjE0LjY0di41MzNjMCAxLjA2Ny0uMTA2LjY0LjY0IDEuMDY3IDEuNDk0Ljg1MyAyLjM0NyAzLjA5MyAyLjc3NCA2LjE4Ny42NCA0LjQ4IDIuODggNy4zNiA2LjQgOC42NCAzLjMwNiAxLjI4IDcuMDQgMS4xNzMgMTAuMzQ2LS4xMDcgMS44MTQtLjc0NyAzLjQxNC0xLjgxMyA0LjY5NC0zLjczMyAyLjI0LTMuMiAxLjQ5My01LjIyNyAyLjY2Ni04IC45Ni0yLjQ1NCAzLjczNC0yLjQ1NCA0LjggMCAxLjE3NCAyLjc3My40MjcgNC44IDIuNjY3IDggMS4yOCAxLjgxMyAyLjg4IDIuOTg2IDQuNjkzIDMuNzMzIDMuMzA3IDEuMjggNy4wNCAxLjM4NyAxMC4zNDcuMTA3IDMuNjI3LTEuMzg3IDUuNzYtNC4xNiA2LjQtOC42NC40MjctMy4wOTQgMS4yOC01LjMzNCAyLjc3My02LjE4Ny43NDctLjQyNy42NCAwIC42NC0xLjA2N3YtLjUzM2MwLS40MjcgMC0uNTMzLS4zMi0uNjQtLjQyNi0uMjEzLS44NTMtLjQyNy0xLjI4LS41MzMtMy44NC0xLjM4Ny0xMS40MTMtMS4zODctMTQuOTMzLTEuMDY3LTMuNzMzLjMyLTYuODI3IDEuMTczLTkuMzg3IDIuNDUzIiBmaWxsPSIjNDk0OTQ5Ii8+PHBhdGggZD0iTTQ1LjQ0IDQyLjk4N2MtOC42NCA2LjA4LTE4LjI0IDUuOTczLTI2Ljg4IDAtMS4wNjctLjc0Ny0xLjkyLjUzMy0xLjI4IDEuNzA2IDIuNjY3IDQuMjY3IDcuODkzIDguMjE0IDE0LjcyIDguMjE0czEyLjA1My0zLjg0IDE0LjcyLTguMjE0Yy42NC0xLjE3My0uMjEzLTIuNDUzLTEuMjgtMS43MDYiIGZpbGw9IiM2NjRlMjciLz48L2c+PC9zdmc+)
                }

                .csh-smiley[data-name=crying] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiM2NWIxZWYiPjxlbGxpcHNlIGN4PSIxNi41MzMiIGN5PSI2MS43NiIgcng9IjEzLjMzMyIgcnk9IjEuNiIvPjxlbGxpcHNlIGN4PSI0NC44IiBjeT0iNjIuMDgiIHJ4PSIxOS4yIiByeT0iMS45MiIvPjwvZz48Y2lyY2xlIGN4PSIzMiIgY3k9IjMyIiBmaWxsPSIjZmZkZDY3IiByPSIzMiIvPjxwYXRoIGQ9Ik00NS41NDcgNDYuOTMzYy0xLjQ5NC0zLjg0LTUuMTItNi40LTEzLjU0Ny02LjQtOC41MzMgMC0xMi4wNTMgMi41Ni0xMy41NDcgNi40LS43NDYgMi4wMjcuMzIgNS4zMzQuMzIgNS4zMzRDMjAuMTYgNTYuNDI3IDE5Ljk0NyA1Ny42IDMyIDU3LjZzMTEuODQtMS4xNzMgMTMuMjI3LTUuMzMzYzAgMCAxLjE3My0zLjMwNy4zMi01LjMzNCIgZmlsbD0iIzY2NGUyNyIvPjxwYXRoIGQ9Ik00MS42IDQ1Ljg2N2EuODMuODMgMCAwIDAtLjIxMy0uODU0UzM5LjI1MyA0Mi42NjcgMzIgNDIuNjY3cy05LjM4NyAyLjM0Ni05LjM4NyAyLjM0NmMtLjIxMy4xMDctLjIxMy41MzQtLjIxMy44NTRsLjIxMy42NGMuMTA3LjMyLjMyLjUzMy41MzQuNTMzaDE3LjcwNmMuMjE0IDAgLjUzNC0uMjEzLjUzNC0uNTMzeiIgZmlsbD0iI2ZmZiIvPjxnIGZpbGw9IiM2NWIxZWYiPjxwYXRoIGQ9Ik00NS4zMzMgNjIuNGg3LjI1NGM4Ljc0Ni0xMC41Ni0xLjYtMjEuMzMzLjk2LTMxLjc4Ny0yLjQ1NCAwLTQuOTA3IDIuNjY3LTcuMjU0IDIuNjY3LTMuNDEzIDEwLjEzMyA3Ljc4NyAxOC41Ni0uOTYgMjkuMTJNMTguNjY3IDYyLjRoLTcuMjU0Yy04Ljc0Ni0xMC41NiAxLjYtMjEuMzMzLS45Ni0zMS43ODcgMi40NTQgMCA0LjkwNyAyLjY2NyA3LjI1NCAyLjY2NyAzLjQxMyAxMC4xMzMtNy43ODcgMTguNTYuOTYgMjkuMTIiLz48L2c+PGcgZmlsbD0iIzkxNzUyNCI+PHBhdGggZD0iTTQxLjI4IDE3LjM4N2MzLjIgMy4yIDcuNjggNC44IDEyLjE2IDQuMzczLjY0LS4xMDcuOTYgMi4yNC4yMTMgMi4zNDctNS4yMjYuNDI2LTEwLjM0Ni0xLjM4Ny0xMy45NzMtNS4xMi0uNjQtLjUzNCAxLjE3My0yLjAyNyAxLjYtMS42TTEwLjY2NyAyMS43NmM0LjQ4LjQyNyA4Ljk2LTEuMTczIDEyLjE2LTQuMzczLjQyNi0uNDI3IDIuMjQgMS4wNjYgMS43MDYgMS42LTMuNjI2IDMuNzMzLTguODUzIDUuNTQ2LTEzLjk3MyA1LjEyLS45NiAwLS41MzMtMi4zNDcuMTA3LTIuMzQ3Ii8+PC9nPjxnIGZpbGw9IiM2NjRlMjciPjxwYXRoIGQ9Ik0zNi4xNiAzMC4xODdjNC40OCA4LjUzMyAxMy41NDcgOC41MzMgMTguMDI3IDAgLjIxMy0uNDI3LS4zMi0uNjQtMS4wNjctMS4wNjctNC40OCAzLjUyLTExLjg0IDMuMi0xNS44OTMgMC0uNjQuNDI3LTEuMjguNjQtMS4wNjcgMS4wNjdNOS44MTMgMzAuMTg3YzQuNDggOC41MzMgMTMuNTQ3IDguNTMzIDE4LjAyNyAwIC4yMTMtLjQyNy0uMzItLjY0LTEuMDY3LTEuMDY3LTQuNDggMy41Mi0xMS44NCAzLjItMTUuODkzIDAtLjc0Ny40MjctMS4yOC42NC0xLjA2NyAxLjA2NyIvPjwvZz48L2c+PC9zdmc+)
                }

                .csh-smiley[data-name=embarrassed] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxwYXRoIGQ9Ik02NCAzMmMwIDE3LjcwNy0xNC4yOTMgMzItMzIgMzJTMCA0OS43MDcgMCAzMiAxNC4yOTMgMCAzMiAwczMyIDE0LjI5MyAzMiAzMnoiIGZpbGw9IiNmZmRkNjciLz48ZyBmaWxsPSIjNjY0ZTI3Ij48cGF0aCBkPSJNNTUuMzYgMjkuMDEzYy0zLjYyNy00LjE2LTE0LjkzMy0yLjY2Ni0xOC4zNDcgMi45ODctLjIxMy40MjcuNDI3IDEuMDY3IDEuMTc0IDEuNDkzIDIuMjQtMS42IDQuOTA2LTIuNDUzIDcuNjgtMi42NjYgMCAyLjk4NiAyLjM0NiA1LjQ0IDUuMzMzIDUuNDQgNC4yNjcgMCA2LjE4Ny00LjggNC4xNi03LjI1NE0yNi4xMzMgMjkuMDEzQzIyLjYxMyAyNC44NTMgMTEuMiAyNi4zNDcgNy43ODcgMzJjLS4yMTQuNDI3LjQyNiAxLjA2NyAxLjE3MyAxLjQ5MyAyLjI0LTEuNiA0LjkwNy0yLjQ1MyA3LjY4LTIuNjY2IDAgMi45ODYgMi4zNDcgNS40NCA1LjMzMyA1LjQ0IDQuMjY3IDAgNi4yOTQtNC44IDQuMTYtNy4yNTRNNDAuODUzIDQ1LjU0N2MtNi4xODYtMS42LTEyLjgtLjQyNy0xOC4wMjYgMy4yLTEuMjguOTYgMS4xNzMgNC4yNjYgMi40NTMgMy40MTMgMy40MTMtMi40NTMgOC45Ni00LjA1MyAxNC42MTMtMi41NiAxLjM4Ny4zMiAyLjU2LTMuNjI3Ljk2LTQuMDUzIi8+PC9nPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=heart] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjUyIiB2aWV3Qm94PSIwIDAgNjQgNTIiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNNjMuMDA2IDEwLjg2N0M1Ni4xODYtNy4yNDcgMzQuMDI0Ljg1MSAzMiA5LjkxIDI5LjIzLjMxOSA3LjYtNi44MjEuOTkyIDEwLjg2Ny02LjM2IDMwLjU4IDI5LjQ0MiA0OC4yNjcgMzIgNTEuMTQ1IDM0LjU1NyA0OC44IDcwLjM2IDMwLjI2IDYzLjAwNiAxMC44NjciIGZpbGw9IiNmZjVhNzkiIGZpbGwtcnVsZT0iZXZlbm9kZCIvPjwvc3ZnPg==)
                }

                .csh-smiley[data-name=laughing] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGcgZmlsbD0iIzY2NGUyNyI+PHBhdGggZD0iTTUzLjAxMyAxOC41NmMuNjQuMzIuMzIgMS4wNjctLjIxMyAxLjE3My0yLjg4LjQyNy01Ljg2Ny45Ni04Ljg1MyAyLjU2IDQuMjY2Ljc0NyA3LjY4IDIuODggOS42IDUuMTIuNDI2LjUzNC0uMTA3IDEuMTc0LS41MzQgMS4wNjctNS4xMi0xLjgxMy0xMC4zNDYtMi44OC0xNi44NTMtMi4xMzMtLjUzMyAwLS45Ni0uMjE0LS44NTMtLjc0NyAxLjcwNi03Ljc4NyAxMS42MjYtMTAuNjY3IDE3LjcwNi03LjA0TTEwLjk4NyAxOC41NmMtLjY0LjMyLS4zMiAxLjA2Ny4yMTMgMS4xNzMgMi44OC40MjcgNS44NjcuOTYgOC44NTMgMi41Ni00LjI2Ni43NDctNy42OCAyLjg4LTkuNiA1LjEyLS40MjYuNTM0LjEwNyAxLjE3NC41MzQgMS4wNjcgNS4xMi0xLjgxMyAxMC4zNDYtMi44OCAxNi44NTMtMi4xMzMuNTMzIDAgLjk2LS4yMTQuODUzLS43NDctMS43MDYtNy43ODctMTEuNjI2LTEwLjY2Ny0xNy43MDYtNy4wNE01MC44OCAzNC41NmMtLjQyNy0uNTMzLTEuMTczLS40MjctMi4wMjctLjQyN0gxNS4xNDdjLS44NTQgMC0xLjYtLjEwNi0yLjAyNy40MjctNC4xNiA1LjMzMy43NDcgMjAuOTA3IDE4Ljg4IDIwLjkwN1M1NS4wNCAzOS44OTMgNTAuODggMzQuNTYiLz48L2c+PHBhdGggZD0iTTMzLjkyIDQyLjM0N2MtLjY0IDAtMS42LjUzMy0xLjE3MyAyLjEzMy4yMTMuNzQ3IDEuMjggMS43MDcgMS4yOCAyLjk4NyAwIDIuNTYtNC4wNTQgMi41Ni00LjA1NCAwIDAtMS4yOCAxLjA2Ny0yLjEzNCAxLjI4LTIuOTg3LjMyLTEuNDkzLS42NC0yLjEzMy0xLjE3My0yLjEzMy0xLjcwNyAwLTQuMzczIDEuODEzLTQuMzczIDQuOTA2IDAgMy40MTQgMi44OCA2LjE4NyA2LjQgNi4xODdzNi40LTIuNzczIDYuNC02LjE4N2MtLjEwNy0yLjk4Ni0yLjg4LTQuOC00LjU4Ny00LjkwNiIgZmlsbD0iIzRjMzUyNiIvPjxwYXRoIGQ9Ik0yMy43ODcgNTEuOTQ3YzIuMzQ2IDEuMDY2IDUuMTIgMS42IDguMjEzIDEuNnM1Ljg2Ny0uNjQgOC4yMTMtMS42Yy0yLjI0LTEuMTc0LTUuMDEzLTEuODE0LTguMjEzLTEuODE0cy01Ljk3My42NC04LjIxMyAxLjgxNCIgZmlsbD0iI2ZmNzE3ZiIvPjxwYXRoIGQ9Ik00OCAzNi4yNjdIMTYuMTA3Yy0yLjI0IDAtMi4yNCA0LjI2Ni0uMTA3IDQuMjY2aDMyYzIuMTMzIDAgMi4xMzMtNC4yNjYgMC00LjI2NiIgZmlsbD0iI2ZmZiIvPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=sad] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGcgZmlsbD0iIzY2NGUyNyIgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoMTMuODY3IDIwLjI2NykiPjxjaXJjbGUgY3g9IjUuODY3IiBjeT0iNS45NzMiIHI9IjUuMzMzIi8+PGNpcmNsZSBjeD0iMzAuNCIgY3k9IjUuOTczIiByPSI1LjMzMyIvPjxwYXRoIGQ9Ik04LjUzMyAyOC4zNzNjNi4xODctNS4xMiAxMy4wMTQtNS4xMiAxOS4yIDAgLjc0Ny42NCAxLjM4Ny0uNDI2Ljg1NC0xLjM4Ni0xLjkyLTMuNjI3LTUuNjU0LTYuOTM0LTEwLjQ1NC02LjkzNFM5LjQ5MyAyMy4zNiA3LjY4IDI2Ljk4N2MtLjUzMy45Ni4xMDcgMi4wMjYuODUzIDEuMzg2Ii8+PC9nPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=sick] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGcgZmlsbD0iIzkxNzUyNCI+PHBhdGggZD0iTTIxLjk3MyAxNy4yOGMtMy40MTMgMi44OC04IDQuMTYtMTIuNDggMy4zMDctLjY0LS4xMDctMS4xNzMgMi4xMzMtLjQyNiAyLjM0NiA1LjEyLjk2IDEwLjQ1My0uNTMzIDE0LjQtMy44NC41MzMtLjUzMy0xLjA2Ny0yLjI0LTEuNDk0LTEuODEzTTU0LjUwNyAyMC40OGMtNC40OC43NDctOS4wNjctLjQyNy0xMi40OC0zLjMwNy0uNDI3LS40MjYtMi4xMzQgMS4yOC0xLjQ5NCAxLjgxNCAzLjk0NyAzLjQxMyA5LjI4IDQuOCAxNC40IDMuODQuNzQ3LS4yMTQuMjE0LTIuNDU0LS40MjYtMi4zNDciLz48L2c+PGcgZmlsbD0iIzY2NGUyNyI+PHBhdGggZD0iTTQ3LjU3MyA0My4wOTNjLS41MzMtLjY0LTEuNi0uODUzLTIuMzQ2LS4zMmwtNC40OCAyLjk4N2MtLjc0Ny41MzMtMS45Mi40MjctMi41Ni0uMTA3bC00LjkwNy00LjE2Yy0uNjQtLjUzMy0xLjcwNy0uNTMzLTIuNDUzIDBsLTQuOTA3IDQuMTZjLS42NC41MzQtMS44MTMuNjQtMi41Ni4xMDdsLTQuNTg3LTIuOTg3Yy0uNzQ2LS41MzMtMS44MTMtLjMyLTIuMzQ2LjMybC00LjY5NCA1LjU0N2MtLjUzMy42NC0uNDI2Ljg1My4zMi40MjdsNC4wNTQtMi4yNGMuNzQ2LS40MjcgMS45Mi0uMzIgMi41Ni4zMmw0LjkwNiA0LjhjLjY0LjY0IDEuNzA3LjY0IDIuNDU0LjEwNmw0LjgtMy42MjZhMi4yNDggMi4yNDggMCAwIDEgMi41NiAwbDQuNjkzIDMuNjI2Yy43NDcuNTM0IDEuODEzLjQyNyAyLjQ1My0uMTA2bDQuOTA3LTQuOGMuNjQtLjY0IDEuODEzLS43NDcgMi41Ni0uMzJsNC4wNTMgMi4yNGMuNzQ3LjQyNi45Ni4yMTMuMzItLjQyN3pNNTMuMDEzIDI3Ljg0Yy42NC4zMi4zMiAxLjA2Ny0uMjEzIDEuMTczLTIuODguNDI3LTUuODY3Ljk2LTguODUzIDIuNTYgNC4yNjYuNzQ3IDcuNjggMi44OCA5LjYgNS4xMi40MjYuNTM0LS4xMDcgMS4xNzQtLjUzNCAxLjA2Ny01LjEyLTEuODEzLTEwLjM0Ni0yLjg4LTE2Ljg1My0yLjEzMy0uNTMzIDAtLjk2LS4yMTQtLjg1My0uNzQ3IDEuNzA2LTcuNzg3IDExLjYyNi0xMC42NjcgMTcuNzA2LTcuMDRNMTAuOTg3IDI3Ljg0Yy0uNjQuMzItLjMyIDEuMDY3LjIxMyAxLjE3MyAyLjg4LjQyNyA1Ljg2Ny45NiA4Ljg1MyAyLjU2LTQuMjY2Ljc0Ny03LjY4IDIuODgtOS42IDUuMTItLjQyNi41MzQuMTA3IDEuMTc0LjUzNCAxLjA2NyA1LjEyLTEuODEzIDEwLjM0Ni0yLjg4IDE2Ljg1My0yLjEzMy41MzMgMCAuOTYtLjIxNC44NTMtLjc0Ny0xLjcwNi03Ljc4Ny0xMS42MjYtMTAuNjY3LTE3LjcwNi03LjA0Ii8+PC9nPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=small-smile] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGcgZmlsbD0iIzY2NGUyNyIgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoMTMuODY3IDIwLjI2NykiPjxjaXJjbGUgY3g9IjUuODY3IiBjeT0iNS45NzMiIHI9IjUuMzMzIi8+PGNpcmNsZSBjeD0iMzAuNCIgY3k9IjUuOTczIiByPSI1LjMzMyIvPjxwYXRoIGQ9Ik0zMS41NzMgMjAuNTg3Yy04LjY0IDYuMDgtMTguMjQgNS45NzMtMjYuODggMC0xLjA2Ni0uNzQ3LTEuOTIuNTMzLTEuMjggMS43MDYgMi42NjcgNC4yNjcgNy44OTQgOC4yMTQgMTQuNzIgOC4yMTQgNi44MjcgMCAxMi4wNTQtMy44NCAxNC43Mi04LjIxNC42NC0xLjE3My0uMjEzLTIuNDUzLTEuMjgtMS43MDYiLz48L2c+PC9nPjwvc3ZnPg==)
                }

                .csh-smiley[data-name=big-smile] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PHBhdGggZD0iTTUwLjg4IDM0LjU2Yy0uNDI3LS41MzMtMS4xNzMtLjQyNy0yLjAyNy0uNDI3SDE1LjE0N2MtLjg1NCAwLTEuNi0uMTA2LTIuMDI3LjQyNy00LjE2IDUuMzMzLjc0NyAyMC45MDcgMTguODggMjAuOTA3UzU1LjA0IDM5Ljg5MyA1MC44OCAzNC41NiIgZmlsbD0iIzY2NGUyNyIvPjxwYXRoIGQ9Ik0zMy45MiA0Mi4zNDdjLS42NCAwLTEuNi41MzMtMS4xNzMgMi4xMzMuMjEzLjc0NyAxLjI4IDEuNzA3IDEuMjggMi45ODcgMCAyLjU2LTQuMDU0IDIuNTYtNC4wNTQgMCAwLTEuMjggMS4wNjctMi4xMzQgMS4yOC0yLjk4Ny4zMi0xLjQ5My0uNjQtMi4xMzMtMS4xNzMtMi4xMzMtMS43MDcgMC00LjM3MyAxLjgxMy00LjM3MyA0LjkwNiAwIDMuNDE0IDIuODggNi4xODcgNi40IDYuMTg3czYuNC0yLjc3MyA2LjQtNi4xODdjLS4xMDctMi45ODYtMi44OC00LjgtNC41ODctNC45MDYiIGZpbGw9IiM0YzM1MjYiLz48cGF0aCBkPSJNMjMuNzg3IDUxLjk0N2MyLjM0NiAxLjA2NiA1LjEyIDEuNiA4LjIxMyAxLjZzNS44NjctLjY0IDguMjEzLTEuNmMtMi4yNC0xLjE3NC01LjAxMy0xLjgxNC04LjIxMy0xLjgxNHMtNS45NzMuNjQtOC4yMTMgMS44MTQiIGZpbGw9IiNmZjcxN2YiLz48cGF0aCBkPSJNNDggMzYuMjY3SDE2LjEwN2MtMi4yNCAwLTIuMjQgNC4yNjYtLjEwNyA0LjI2NmgzMmMyLjEzMyAwIDIuMTMzLTQuMjY2IDAtNC4yNjYiIGZpbGw9IiNmZmYiLz48ZyBmaWxsPSIjNjY0ZTI3Ij48Y2lyY2xlIGN4PSIxOS43MzMiIGN5PSIyMi40IiByPSI1LjMzMyIvPjxjaXJjbGUgY3g9IjQ0LjI2NyIgY3k9IjIyLjQiIHI9IjUuMzMzIi8+PC9nPjwvZz48L3N2Zz4=)
                }

                .csh-smiley[data-name=thumbs-up] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjYzIiB2aWV3Qm94PSIwIDAgNDMgNjMiIHdpZHRoPSI0MyIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxwYXRoIGQ9Ik0yMC44MjMgMjYuMzM0cy00LjYxNi45NDUtLjg0LTYuOTI0YzIuNzI4LTUuNjY2IDIuNDE0LTEyLjI3NiAwLTE1LjczOC0zLjk4Ni01LjU2LTExLjY0NS0zLjc3Ny0xMC44MDYtLjUyNCAyLjcyOCAxMS4wMTYtMy40NjIgMTQuMzczLTYuNjEgMjEuMjk4LTMuMjUyIDcuMDMtMi45MzcgMTcuMTAyLTEuNDY5IDI2LjAyLjk0NSA1LjU2IDMuMzU4IDEyLjQ4NSAxMi4wNjYgMTIuNDg1SDI1LjIzeiIgZmlsbD0iI2ZmZGQ2NyIvPjxwYXRoIGQ9Ik0xNC41MjggNjEuMzc3Yy04LjcwOCAwLTEwLjU5Ny02LjkyNS0xMS41NDEtMTIuNDg1QzEuNTE4IDM5Ljk3NCAxLjMwOCAzMi44MzkgNC4xNCAyNS42YzMuMTQ4LTcuODY5IDYuNC04LjA3OSA2LjQtMjMuNjA3IDAtLjczNC40Mi0xLjI1OS44NC0xLjY3OC0xLjQ3LjUyNC0yLjMwOSAxLjM2NC0yLjMwOSAyLjYyMyAwIDExLjY0Ni0zLjI1MiAxNC40NzgtNi40IDIxLjUwOC0zLjM1NyA3LjAzLTMuMDQyIDE3LjEwMi0xLjU3NCAyNi4wMi45NDUgNS41NiAzLjM1OCAxMi40ODUgMTIuMDY2IDEyLjQ4NUgyNS4yM3YtMS41NzR6IiBmaWxsPSIjZWJhMzUyIi8+PHBhdGggZD0iTTM1LjcyMSAzNS40NjJIMjAuODIzYy01LjI0NiAwLTUuMjQ2LTkuMTI4IDAtOS4xMjhoMTQuODk4YzUuMjQ2IDAgNS4yNDYgOS4xMjggMCA5LjEyOCIgZmlsbD0iI2ZmZGQ2NyIvPjxwYXRoIGQ9Ik0zNi44NzUgMzMuOTkzSDIxLjk3N2MtMy41NjcgMC00LjYxNi00LjE5Ni0zLjQ2Mi02LjgyLTIuODMzIDIuMjA0LTEuOTk0IDguMzk0IDIuMjAzIDguMzk0aDE1LjAwM2MxLjY3OSAwIDIuODMzLS45NDQgMy40NjMtMi4zMDgtLjYzLjQyLTEuMzY0LjczNC0yLjMwOS43MzQiIGZpbGw9IiNlYmEzNTIiLz48cGF0aCBkPSJNMzcuMjk1IDQ0LjY5NUgxOS40NmMtNi4yOTUgMC02LjI5NS05LjEyOCAwLTkuMTI4SDM3LjRjNi4xOSAwIDYuMTkgOS4xMjgtLjEwNSA5LjEyOCIgZmlsbD0iI2ZmZGQ2NyIvPjxwYXRoIGQ9Ik0zOC43NjQgNDMuMTIxSDIwLjgyM2MtNC4xOTcgMC01LjU2LTQuMTk2LTQuMDkyLTYuODItMy4zNTcgMi4yMDQtMi40MTMgOC4zOTQgMi43MjggOC4zOTRIMzcuNGMxLjk5MyAwIDMuMzU3LS45NDQgNC4wOTItMi4zMDhhNS41MzkgNS41MzkgMCAwIDEtMi43MjguNzM0IiBmaWxsPSIjZWJhMzUyIi8+PHBhdGggZD0iTTM1LjYxNiA1My44MjNIMjAuNTA4Yy01LjI0NiAwLTUuMjQ2LTkuMTI4IDAtOS4xMjhoMTUuMTA4YzUuMzUxIDAgNS4zNTEgOS4xMjggMCA5LjEyOCIgZmlsbD0iI2ZmZGQ2NyIvPjxwYXRoIGQ9Ik0zNi44NzUgNTIuMjVIMjEuNjYyYy0zLjU2NyAwLTQuNzIxLTQuMTk4LTMuNDYyLTYuOTI1LTIuODMzIDIuMjAzLTIuMDk4IDguMzkzIDIuMzA4IDguMzkzaDE1LjEwOGMxLjY4IDAgMi44MzMtLjk0NCAzLjQ2My0yLjMwOC0uNTI1LjYzLTEuMzY0Ljg0LTIuMjA0Ljg0IiBmaWxsPSIjZWJhMzUyIi8+PHBhdGggZD0iTTM0LjA0MyA2Mi45NWgtOS43NThjLTUuNjY1IDAtNS42NjUtOS4xMjcgMC05LjEyN2g5Ljc1OGM1LjY2NSAwIDUuNjY1IDkuMTI4IDAgOS4xMjgiIGZpbGw9IiNmZmRkNjciLz48cGF0aCBkPSJNMzUuMzAyIDYxLjQ4MmgtOS43NThjLTMuNzc3IDAtNS4wMzYtNC4xOTctMy42NzItNi45MjUtMy4wNDIgMi4yMDQtMi4yMDMgOC4zOTQgMi40MTMgOC4zOTRoOS43NThjMS44ODggMCAzLjA0Mi0uOTQ0IDMuNjcyLTIuMzA4LS42My41MjQtMS40Ny44MzktMi40MTMuODM5IiBmaWxsPSIjZWJhMzUyIi8+PC9nPjwvc3ZnPg==)
                }

                .csh-smiley[data-name=surprised] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGNpcmNsZSBjeD0iMTguMTMzIiBjeT0iMjguOCIgZmlsbD0iI2ZmZiIgcj0iMTEuNzMzIi8+PHBhdGggZD0iTTIzLjQ2NyAyOC44YzAgMi45ODctMi4zNDcgNS4zMzMtNS4zMzQgNS4zMzMtMi45ODYgMC01LjMzMy0yLjM0Ni01LjMzMy01LjMzM3MyLjM0Ny01LjMzMyA1LjMzMy01LjMzM2MyLjk4NyAwIDUuMzM0IDIuMzQ2IDUuMzM0IDUuMzMzIiBmaWxsPSIjNjY0ZTI3Ii8+PHBhdGggZD0iTTU3LjYgMjguOGExMS43IDExLjcgMCAwIDEtMTEuNzMzIDExLjczM2MtNi41MDcgMC0xMS43MzQtNS4yMjYtMTEuNzM0LTExLjczM3M1LjIyNy0xMS43MzMgMTEuNzM0LTExLjczM0ExMS43IDExLjcgMCAwIDEgNTcuNiAyOC44IiBmaWxsPSIjZmZmIi8+PHBhdGggZD0iTTUxLjIgMjguOGMwIDIuOTg3LTIuMzQ3IDUuMzMzLTUuMzMzIDUuMzMzLTIuOTg3IDAtNS4zMzQtMi4zNDYtNS4zMzQtNS4zMzNzMi4zNDctNS4zMzMgNS4zMzQtNS4zMzNjMi45ODYgMCA1LjMzMyAyLjM0NiA1LjMzMyA1LjMzMyIgZmlsbD0iIzY2NGUyNyIvPjxnIGZpbGw9IiM5MTc1MjQiPjxwYXRoIGQ9Ik01MS40MTMgMTQuNzJjLTMuNDEzLTIuODgtOC00LjE2LTEyLjQ4LTMuMzA3LS42NC4xMDctMS4xNzMtMi4xMzMtLjQyNi0yLjM0NiA1LjEyLS45NiAxMC40NTMuNTMzIDE0LjQgMy44NC42NC41MzMtMS4wNjcgMi4yNC0xLjQ5NCAxLjgxM00yNS4wNjcgMTEuMmMtNC40OC0uNzQ3LTkuMDY3LjQyNy0xMi40OCAzLjMwNy0uNDI3LjQyNi0yLjEzNC0xLjI4LTEuNDk0LTEuODE0IDMuOTQ3LTMuNDEzIDkuMjgtNC44IDE0LjQtMy44NC43NDcuMjE0LjIxNCAyLjQ1NC0uNDI2IDIuMzQ3Ii8+PC9nPjxjaXJjbGUgY3g9IjMyIiBjeT0iNTAuMTMzIiBmaWxsPSIjNjY0ZTI3IiByPSI5LjYiLz48cGF0aCBkPSJNMjUuNiA0Ni45MzNjMS4yOC0yLjU2IDMuNjI3LTQuMjY2IDYuNC00LjI2NnM1LjEyIDEuNzA2IDYuNCA0LjI2NnoiIGZpbGw9IiNmZmYiLz48L2c+PC9zdmc+)
                }

                .csh-smiley[data-name=tongue] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxwYXRoIGQ9Ik02NCAzMmMwIDE3LjcwNy0xNC4yOTMgMzItMzIgMzJTMCA0OS43MDcgMCAzMiAxNC4yOTMgMCAzMiAwczMyIDE0LjI5MyAzMiAzMnoiIGZpbGw9IiNmZmRkNjciLz48cGF0aCBkPSJNNDIuNjY3IDQ4Ljk2Yy01LjMzNC01LjMzMy0yLjk4Ny0yLjk4NyAyLjY2Ni04LjY0IDUuNjU0LTUuNjUzIDMuMzA3LTguMTA3IDguNjQtMi42NjcgNS4zMzQgNS4zMzQgNS41NDcgMTAuNTYgMi4zNDcgMTMuNzYtMy4wOTMgMy4wOTQtOC4zMiAyLjg4LTEzLjY1My0yLjQ1MyIgZmlsbD0iI2ZmNzE3ZiIvPjxwYXRoIGQ9Ik00Ni41MDcgMzkuMTQ3bDcuMjUzIDkuNi05LjQ5My03LjI1NHoiIGZpbGw9IiNlMjU5NmMiLz48ZyBmaWxsPSIjNjY0ZTI3Ij48cGF0aCBkPSJNMjguMjY3IDI0LjQyN2MtMi4wMjctNS40NC01LjAxNC04LjIxNC04LTguMjE0LTIuOTg3IDAtNS45NzQgMi43NzQtOCA4LjIxNC0uMjE0LjUzMy44NTMgMS40OTMgMS4zODYuOTYgMS45Mi0yLjAyNyA0LjI2Ny0yLjg4IDYuNjE0LTIuODggMi4zNDYgMCA0LjY5My44NTMgNi42MTMgMi44OC42NC41MzMgMS42LS40MjcgMS4zODctLjk2TTUxLjYyNyAyNC40MjdjLTIuMDI3LTUuNDQtNS4wMTQtOC4yMTQtOC04LjIxNC0yLjk4NyAwLTUuOTc0IDIuNzc0LTggOC4yMTQtLjIxNC41MzMuODUzIDEuNDkzIDEuMzg2Ljk2IDEuOTItMi4wMjcgNC4yNjctMi44OCA2LjYxNC0yLjg4IDIuMzQ2IDAgNC42OTMuODUzIDYuNjEzIDIuODguNTMzLjUzMyAxLjYtLjQyNyAxLjM4Ny0uOTZNNDkuMTczIDMzLjA2N0M0NC41ODcgMzkuNTczIDM5LjA0IDQxLjE3MyAzMiA0MS4xNzNzLTEyLjU4Ny0xLjYtMTcuMTczLTguMTA2Yy0uNjQtLjg1NC0yLjM0Ny0uMzItMS45Mi45NiAyLjQ1MyA4LjUzMyAxMC42NjYgMTMuNTQ2IDE5LjIgMTMuNTQ2IDguNTMzIDAgMTYuNzQ2LTUuMDEzIDE5LjItMTMuNTQ2LjIxMy0xLjI4LTEuNDk0LTEuODE0LTIuMTM0LS45NiIvPjwvZz48L2c+PC9zdmc+)
                }

                .csh-smiley[data-name=winking] {
                    background-image: url(data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjY0IiB2aWV3Qm94PSIwIDAgNjQgNjQiIHdpZHRoPSI2NCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIGZpbGw9IiNmZmRkNjciIHI9IjMyIi8+PGNpcmNsZSBjeD0iMjEuNjUzIiBjeT0iMzEuNTczIiBmaWxsPSIjNjY0ZTI3IiByPSI1LjMzMyIvPjxnIGZpbGw9IiM5MTc1MjQiPjxwYXRoIGQ9Ik01Mi40OCAyNy4yYy0zLjQxMy0yLjg4LTgtNC4xNi0xMi40OC0zLjMwNy0uNjQuMTA3LTEuMTczLTIuMTMzLS40MjctMi4zNDYgNS4xMi0uOTYgMTAuNDU0LjUzMyAxNC40IDMuODQuNjQuNTMzLTEuMDY2IDIuMjQtMS40OTMgMS44MTNNMjQgMTcuOTJjLTQuNDgtLjc0Ny05LjA2Ny40MjctMTIuNDggMy4zMDctLjQyNy40MjYtMi4xMzMtMS4yOC0xLjQ5My0xLjgxNCAzLjk0Ni0zLjQxMyA5LjI4LTQuOCAxNC40LTMuODQuNzQ2LjIxNC4yMTMgMi40NTQtLjQyNyAyLjM0NyIvPjwvZz48ZyBmaWxsPSIjNjY0ZTI3Ij48cGF0aCBkPSJNNTEuNDEzIDM0LjQ1M0M0OS42IDMwLjcyIDQ2LjcyIDI4LjggNDMuOTQ3IDI4LjhjLTIuNzc0IDAtNS41NDcgMS45Mi03LjQ2NyA1LjY1My0uMjEzLjQyNy43NDcgMS4wNjcgMS4yOC42NCAxLjgxMy0xLjM4NiAzLjk0Ny0xLjkyIDYuMTg3LTEuOTJzNC4zNzMuNTM0IDYuMTg2IDEuOTJjLjQyNy4zMiAxLjM4Ny0uMzIgMS4yOC0uNjRNNDQuOTA3IDQyLjg4Yy03LjM2IDMuODQtMTcuNDk0IDMuMDkzLTIwLjM3NCAzLjA5My0uNzQ2IDAtMS4yOC4zMi0xLjA2Ni45NkMyNS42IDU0LjQgNDEuNiA1NC40IDQ1Ljk3MyA0NC4wNTNjLjUzNC0xLjE3My0uMzItMS40OTMtMS4wNjYtMS4xNzMiLz48L2c+PC9nPjwvc3ZnPg==)
                }
                """

            elif len(classes) > 0:
                print(item)
                raise AssertionError('Unexpected classes!')

        if found:
            print(article.prettify())
        return str(article)
