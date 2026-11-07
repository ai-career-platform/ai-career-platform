import json
import unittest
from unittest.mock import patch
from crawler.storage.memory import MemoryPostingStore
from crawler.jobs import import_jobkorea_html as importer


def sample(title='Example job'):
    # Constructed JSON-LD, NOT acquired from JobKorea.
    return '<script type="application/ld+json">' + json.dumps({
        '@type': 'JobPosting', 'title': title,
        'hiringOrganization': {'name': 'Example company'},
        'employmentType': 'FULL_TIME',
        'jobLocation': {'address': {'addressRegion': '서울'}},
    }) + '</script>'


class HtmlImportTests(unittest.TestCase):
    def test_import_repeat_and_update(self):
        store = MemoryPostingStore()
        url = 'https://www.jobkorea.co.kr/Recruit/GI_Read/12345678'
        first = importer.import_pages([(url, sample())], store)
        self.assertEqual(first['inserted'], 1)
        self.assertEqual(importer.import_pages([(url, sample())], store)['unchanged'], 1)
        self.assertEqual(importer.import_pages([(url, sample('Changed'))], store)['updated'], 1)
        self.assertIsNotNone(store.get('jobkorea_imported', '12345678'))
        self.assertIsNone(store.get('jobkorea', '12345678'))

    def test_invalid_page_does_not_stop_batch_and_duplicates_skipped(self):
        url = 'https://www.jobkorea.co.kr/Recruit/GI_Read/12345678'
        report = importer.import_pages([(url, 'broken'), (url, sample()), (url, sample())], MemoryPostingStore())
        self.assertEqual(report['invalid'], 1)
        self.assertEqual(report['inserted'], 1)
        self.assertEqual(report['duplicates'], 1)

    def test_batch_limit(self):
        with self.assertRaises(ValueError):
            importer.import_pages([('', '')] * 11, MemoryPostingStore())

    def test_fetch_obeys_robots_without_posting_request(self):
        with patch.object(importer, '_get', return_value='User-agent: *\nDisallow: /') as get:
            with self.assertRaises(importer.FetchBlocked):
                list(importer.fetch_pages(['https://www.jobkorea.co.kr/Recruit/GI_Read/123']))
        self.assertEqual(get.call_count, 1)

    def test_apex_url_rejected_before_any_request(self):
        with patch.object(importer, '_get') as get:
            with self.assertRaises(ValueError):
                list(importer.fetch_pages(['https://jobkorea.co.kr/Recruit/GI_Read/123']))
        get.assert_not_called()

    def test_blocked_response_stops_later_urls(self):
        urls = ['https://www.jobkorea.co.kr/Recruit/GI_Read/' + str(i) for i in (123, 456)]
        with patch.object(importer, '_get', side_effect=['User-agent: *\nAllow: /', importer.FetchBlocked('403')]) as get:
            with patch.object(importer.time, 'sleep'):
                with self.assertRaises(importer.FetchBlocked):
                    list(importer.fetch_pages(urls))
        self.assertEqual(get.call_count, 2)

    def test_fetch_error_continues_and_throttles(self):
        urls = ['https://www.jobkorea.co.kr/Recruit/GI_Read/' + str(i) for i in (123, 456)]
        with patch.object(importer, '_get', side_effect=['User-agent: *\nAllow: /', OSError('timeout'), sample()]):
            with patch.object(importer.time, 'sleep') as sleep:
                result = list(importer.fetch_pages(urls))
        self.assertEqual(result[0], (urls[0], ''))
        self.assertEqual(result[1], (urls[1], sample()))
        self.assertEqual(sleep.call_count, 2)

    def test_store_failure_does_not_abort_or_poison_duplicate_set(self):
        store = MemoryPostingStore()
        original = store.upsert
        with patch.object(store, 'upsert', side_effect=[RuntimeError('secret'), 'inserted']):
            report = importer.import_pages([('https://www.jobkorea.co.kr/Recruit/GI_Read/123', sample())] * 2, store)
        self.assertEqual((report['invalid'], report['inserted']), (1, 1))
        self.assertNotIn('secret', str(report))
