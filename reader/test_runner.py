from django.core.cache import caches
from django.test.runner import DiscoverRunner


class CacheClearingDiscoverRunner(DiscoverRunner):
    def run_suite(self, suite, **kwargs):
        result = super().run_suite(suite, **kwargs)
        return result

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._wrap_result_start_test()

    def _wrap_result_start_test(self):
        original_resultclass = self.test_runner.resultclass

        class CacheClearingResult(original_resultclass):
            def startTest(self, test):
                for alias in caches:
                    caches[alias].clear()
                super().startTest(test)

        self.test_runner.resultclass = CacheClearingResult
