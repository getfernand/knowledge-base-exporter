# -*- coding:utf-8 -*-

from .base import KnowledgeBaseImporter


class Helpscout(KnowledgeBaseImporter):
    def load(self, base_url: str, language=None):
        if not base_url.endswith('/'):
            base_url += '/'

        self.add_language('en', base_url)
        articles = {}

        page = self.retrieve(base_url)
        for cat in page.select('#contentArea .category-list>a.category'):
            cat_page = self.retrieve(cat.attrs['href'])

            category = cat_page.find('section', {'id': 'main-content'})
            categoryHead = category.find('hgroup', {'id': 'categoryHead'})

            current_col = self.save_category(None, {
                'title': categoryHead.find('h1').text.strip(),
                'description': categoryHead.find('p', {'class': 'descrip'}).text.strip()
            })

            for art in category.select('.articleList a'):
                if art.attrs['href'] in articles:
                    self.add_article_to_category(articles[art.attrs['href']], current_col)
                    continue

                art_page = self.retrieve(art.attrs['href'])
                title = art_page.select_one('#main-content article#fullArticle h1').text.strip()
                try:
                    content = self.parse_content(art_page)
                except AssertionError:
                    print(art.attrs['href'])
                    raise

                articles[art.attrs['href']] = self.save_article(
                    current_col,
                    {
                        'title': title,
                        'previous_url': self.get_url(art.attrs['href']),
                        'content': content
                    }
                )

    async def parse_content(self, soup):
        full_article = soup.find('article', {'id': 'fullArticle'})
        full_article.find('h1').decompose()
        full_article.name = 'div'
        del full_article.attrs['id']
        full_article.find('a', {'class': 'printArticle'}).decompose()

        for item in full_article.find_all():
            if 'style' in item.attrs:
                del item.attrs['style']

        for bold in full_article.find_all('b'):
            bold.name = 'strong'

        for img in full_article.find_all('img'):
            # If the parent is a p or div that is empty, we unwrap it
            if img.parent.name in ('p', 'div') and not img.parent.text.strip():
                img.parent.unwrap()

            # If the parent is a heading, we unwrap it
            if img.parent.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                img.parent.unwrap()

            # If the parent is not a figure, we need to wrap it in one
            self.wrap_image_figure(img, soup)

        # Now treating the videos:
        for div in full_article.find_all('div'):
            if 'class' not in div.attrs:
                continue

            for classname in div.attrs['class'][:]:
                if classname in ('u-centralize', 'video', 'video-vimeo', 'video-responsive'):
                    div.attrs['class'].remove(classname)
                elif classname.startswith('callout-'):
                    style = classname[8:]
                    assert style in ('blue'), "Unknown callout style: {}".format(style)
                    # Wrap the div inside a div
                    div.attrs['class'].remove(classname)
                    if style == 'blue':
                        print('Has callout !')
                        div.wrap(soup.new_tag('div', **{'class': 'callout callout--info'}))
                else:
                    raise AssertionError('Unexpected class name: {}'.format(classname))

        for iframe in full_article.find_all('iframe'):
            self.clean_iframe(iframe)

        return str(full_article)
