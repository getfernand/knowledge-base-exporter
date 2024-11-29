#!/bin/python

from argparse import RawTextHelpFormatter
import argparse, json, logging


def export(url, service, output, language=None, pretty=False):
    importer = None
    try:
        service_name = ''.join([x.title() for x in service.split('_')])
        mod = __import__('services.{}'.format(service.lower()), fromlist=[service_name])
        importer = getattr(mod, service_name)()
        assert importer is not None, 'Service {} is not available to be automatically imported yet'.format(service_name)
    except ImportError:
        raise NotImplementedError('Service {} is not available to be automatically imported yet'.format(service_name))

    importer.load(url, language)
    if output:
        params = {}
        if pretty:
            params['indent'] = 4

        output.write(json.dumps(importer.serialize(), **params))
        output.close()
    else:
        print(json.dumps(importer.serialize(), indent=4))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='knowledge-base-exporter',
        formatter_class=RawTextHelpFormatter,
        description='''Build a standardized JSON file from a given Knowledge base URL.
        Currently support the following platforms:
            * Intercom
            * Helpkit
            * Helpscout
            * Next
            * Notion
            * Crisp
            * Freshdesk

        Feel free to make a Pull Request at https://github.com/getfernand/knowledge-base-exporter to add another platform or make any bug fixes.'''
    )

    parser.add_argument('-u', '--url', required=True, help='URL to the knowledge base to export', dest='url')
    parser.add_argument('-s', '--service', required=True, help='Name of the service providing the knowledge base.')
    parser.add_argument('-o', '--output', required=False, default=None, action='store', type=argparse.FileType('w'), help="JSON file to write the exported data")
    parser.add_argument('-l', '--language', required=False, default=None, help='Specific language to process. Defaults to all available.')
    parser.add_argument('-v', '--verbose', help='Set output logging to debug', action='store_const', const=logging.DEBUG, default=logging.WARNING)
    parser.add_argument('--pretty', action='store_true')

    args = vars(parser.parse_args())
    logger = logging.getLogger('knowledge-base-exporter')

    log_level = args.pop('verbose', logging.WARNING)
    logger.setLevel(log_level)
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter('[%(asctime)s] (%(levelname)s) - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    export(**args)
