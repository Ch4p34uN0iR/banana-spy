class TargetOptions:
    def __init__(self, whitelist=set(), blacklist=set(), keywords=set(), max_resp_size=(10 ** 6)):
        self.whitelist     = set(whitelist)
        self.blacklist     = set(blacklist)
        self.keywords      = set(keywords)
        self.max_resp_size = max_resp_size

    def normalize_size(self, size):
        size_map = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB'}
        times_divided = 0
        while size >= 10 ** 3 and times_divided < 3:
            size = round(size / 10 ** 3)
            times_divided += 1
        return '{} {}'.format(size, size_map[times_divided])


class Target:
    def __init__(self, host, port, use_https, top_dir='', options=TargetOptions()):
        self.host  = host
        self.port  = port
        self.top_dir = top_dir

        self.protocol = 'https://'
        if not use_https:
            self.protocol = 'http://'

        self.options = options
        self.max_resp_size = self.options.max_resp_size
        self.max_resp_size = self.options.normalize_size(self.max_resp_size)

        self.url      = '{}{}{}'   .format(self.protocol, self.host, self.top_dir)
        self.full_url = '{}{}:{}{}'.format(self.protocol, self.host, self.port, self.top_dir)

