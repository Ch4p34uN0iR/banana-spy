from bs4                import BeautifulSoup as BS, Comment
from collections        import OrderedDict as odict
from concurrent.futures import ThreadPoolExecutor
from copy               import copy
from datetime           import datetime as dt
from json               import dump, load
from logging            import getLogger
from os                 import path, remove
from pickle             import Pickler, Unpickler
from re                 import compile, match, finditer
from requests           import Session
from requests.adapters  import HTTPAdapter
# from time               import sleep

# TODO:
    # Docstrings and docs in general
    # Use selenium's built-in browser for javascript
    # save full requests, send to module that looks for input points and tests them with polyglots
        # Every parameter submitted within the URL query string
        # Every parameter submitted within the body of a POST request
        # Every cookie
        # Every HTTP header that the application might process:
            # User-Agent, Referer, Accept, Accept-Language, Host
        # Every URL string up to the query string marker
    # mechanism to log in? maintain session? session tests?
    # split crawl() into more methods, if possible, adding debug messages as applicable
    # read from spider config file?
    # option to sleep between requests?
    # ability to specify number of retries on request failures?
    # expose some advanced Requests features? callbacks, auth, etc.
    # make a module to build and search NLTK corpora out of spyder results?

log = getLogger(__name__)

class SpyderOptions:
    def __init__(self, max_workers=1, max_retries=3, load_state=True, results_file='spyder_results.json'):
        self.max_workers  = max_workers
        self.max_retries  = max_retries
        self.load_state   = load_state
        self.results_file = results_file


class Spyder:
    def __init__(self, target, session=None, cleanup_session=True, options=SpyderOptions()):
        self.target          = target
        self.session         = session
        self.cleanup_session = cleanup_session
        self.options         = options

        self.executor         = None
        self.queued_workers   = 0
        self.finished_workers = 0

        self.visited = set()
        self.pending = set()
        self.results = {}

        self.statefile  = 'spyder_state.tmp'
        if self.options.load_state and path.isfile(self.statefile):
            self.load_state()

    def spin(self):
        start_time = dt.now()
        if not self.session:
            self.session = Session()
        http_adapter = HTTPAdapter(max_retries=self.options.max_retries, pool_maxsize=self.options.max_workers)
        self.session.mount('http://', http_adapter)
        self.session.mount('https://', http_adapter)
        self.pending.add(self.target.full_url)
        while self.pending:
            with ThreadPoolExecutor(max_workers=self.options.max_workers) as self.executor:
                workers = [self.executor.submit(self.crawl, full_url)
                           for full_url in self.pending]
            self.pending = self.pending - self.visited
            page = 'page'
            if len(self.visited) > 1:
                page += 's'
            log.info('{} {} visited, {} more found!'.format(len(self.visited), page, len(self.pending)))
            self.save_state()
        time_taken = (dt.now() - start_time).seconds
        log.info('{} pages parsed in {} seconds!'.format(len(self.results), time_taken))

        self.coccoon()

    def load_state(self):
        with open(self.options.results_file, 'r') as f:
            self.results = load(f)
        with open(self.statefile, 'rb') as f:
            u = Unpickler(f)
            self.target          = u.load()
            self.session         = u.load()
            self.cleanup_session = u.load()
            self.options         = u.load()
            self.visited         = u.load()
            self.pending         = u.load()

    def save_state(self):
        with open(self.options.results_file, 'w') as f:
            dump(self.results, f, indent=4, separators=(',', ': '))
        with open(self.statefile, 'wb') as f:
            p = Pickler(f)
            p.dump(self.target         )
            p.dump(self.session        )
            p.dump(self.cleanup_session)
            p.dump(self.options        )
            p.dump(self.visited        )
            p.dump(self.pending        )

    def crawl(self, full_url):
        # Issue HEAD for some preliminary checks
        resp = self.session.head(full_url, allow_redirects=False)
        self.visited.add(full_url)
        page = '[{}] {}'.format(resp.status_code, full_url)
        self.results[page] = {
            'comments': list(),
            # TODO remove keywords if NLTK stuff works better?
            # keywords could remain as a simpler mechanism, especially if NLTK is a separate module
            'keywords': list(),
            'acquired': list(),
            'skipped' : list(),
        }

        # Check scope in case of redirection
        if (resp.is_redirect or resp.is_permanent_redirect) \
        and not self.redirection_in_scope(full_url, resp):
            return
        # Check response size
        if self.huge_response(full_url, resp):
            self.results[page]['skipped'].append(full_url)
            return
        resp = self.session.get(full_url, stream=True)
        # TODO allowed file types?
        # Check response size again, in case the HEAD response had no content-length header
        # This time, the response will be streamed
        if self.huge_response(full_url, resp):
            self.results[page]['skipped'].append(full_url)
            return

        # Rewrite results and record redirects, if any
        prev_url = full_url
        pages = ''
        for r in resp.history:
            pages += '[{}] {}\n'.format(r.status_code, prev_url)
            prev_url = self.normalize_link(r.headers['location'])
        pages += '[{}] {}'.format(resp.status_code, prev_url)
        if page != pages:
            self.results[pages] = self.results.pop(page)

        bs = BS(resp.text, 'html.parser')

        comments = bs.find_all(text=lambda text:isinstance(text, Comment))
        self.results[pages]['comments'] = list(comments)

        for keyword in self.target.options.keywords:
            one28 = '.{0,128}'
            exp = compile(one28 + keyword + one28)
            for hit in finditer(exp, resp.text):
                entry = '{}{}'.format('...', hit.group(0))
                self.results[pages]['keywords'].append(entry)

        # Find and visit every unique link in the page
        links = [atag.get('href') for atag in bs.find_all('a')]
        for link in set(links):
            # Some <a> tags have no href attribute
            if not link:
                continue

            # normalize_link() marks links which are out of scope with an initial '!';
            # additionally, it checks that the link is in scope
            link = self.normalize_link(link)
            entry = link.replace('!', '')
            if link.startswith('!'):
                self.results[pages]['skipped'].append(entry)
                continue

            # Check white/blacklists
            if not self.check_whitelist(link) or not self.check_blacklist(link):
                self.results[pages]['skipped'].append(link)
                continue

            new_full_url = link
            if self.target.port not in link:
                new_full_url = link.replace(self.target.host, '{}:{}'.format(self.target.host, self.target.port))

            self.pending.add(new_full_url)
            self.results[pages]['acquired'].append(new_full_url)

    def redirection_in_scope(self, full_url, response):
        # Should never happen; checking anyway.
        if 'location' not in response.headers:
            log.error('Redirection response contains no Location header; skipping {}\n'.format(full_url))
            return False
        location = response.headers['location']

        # In case the location header is relative
        if self.target.host not in location:
            location = self.normalize_link(location)

        if self.target.host not in location:
            # In case normalize_link() was called
            location = location.replace('!', '')
            log.debug('Redirection out of scope; skipping {} -> {}'.format(full_url, location))
            page = '[{}] {}'.format(response.status_code, full_url)
            self.results[page]['skipped'].append(location)
            return False
        return True

    def huge_response(self, full_url, response):
        resp_size = 0
        if 'content-length' in response.headers:
            resp_size = int(response.headers['content-length'])
        else:
            for line in response.iter_lines():
                resp_size += len(line)
                if resp_size > self.target.options.max_resp_size:
                    break
        if resp_size > self.target.options.max_resp_size:
            log.debug('Response size is {}, which exceeds {}, the current maximum acceptable response size; skipping {}'.format(
                self.target.options.normalize_size(resp_size), self.target.max_resp_size, full_url))
            return True
        return False

    def normalize_link(self, link):
        # Don't care about anchor links
        if '#' in link:
            return '!' + link

        # If it's a relative link, make it absolute
        abs_link = match('https?://', link)
        if not abs_link:
            if not link.startswith('/'):
                link = '/' + link
            if self.target.host not in link:
                link = self.target.host + link
            if self.target.protocol not in link:
                link = self.target.protocol + link

        # Move up directories if necessary
        if '..' in link:
            split_link = link.split('/..')
            parents = split_link[0].split('/')
            for item in split_link:
                if not item and parents[-1] != self.target.host:
                    parents.pop(-1)
            link = '/'.join(parents) + ''.join(split_link[1:])

        # Check scope
        if self.target.host + self.target.top_dir not in link:
            log.debug('Target out of scope; skipping {}'.format(link))
            return '!' + link

        return link

    def check_whitelist(self, link):
        if not self.target.options.whitelist:
            return True
        for item in self.target.options.whitelist:
            if item in link and (self.target.url in link or self.target.full_url in link):
                return True
        log.debug('Page not in whitelist; skipping {}'.format(link))
        return False

    def check_blacklist(self, link):
        if not self.target.options.blacklist:
            return True
        for item in self.target.options.blacklist:
            if item in link:
                log.debug('Page in blacklist; skipping {}'.format(link))
                return False
        return True

    def coccoon(self):
        if self.cleanup_session:
            self.session.close()
            log.info('Session closed!')
        else:
            log.warning('Session remains open!')

        # Sort result lists
        for categories in self.results.values():
            for category, values in categories.items():
                categories[category] = sorted(list(set(values)))

        # Save final results to results_file, if specified
        if self.options.results_file:
            with open(self.options.results_file, 'w') as f:
                dump(self.results, f, indent=4, separators=(',', ': '))
        else:
            log.warning('No output file specified! Results were NOT saved!')

        remove(self.statefile)

