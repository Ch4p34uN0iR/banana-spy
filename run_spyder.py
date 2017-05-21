#! /usr/bin/python3

from argparse import ArgumentParser, RawTextHelpFormatter
from logging import (
    DEBUG      ,
    ERROR      ,
    INFO       ,
    WARNING    ,
    basicConfig,
    getLogger  ,
)
from os import getcwd, path, makedirs
from re import compile, match
from sys import stdout
from target import Target, TargetOptions
from spyder import Spyder, SpyderOptions

log = getLogger(__name__)

def confirm_protocol(protocol):
    if protocol == 'http://':
        default_port = '80'
    if protocol == 'https://':
        default_port = '443'
    if not protocol:
        while not protocol:
            protocol = input('\nNo protocol specified...\n'
                             '  1. Use HTTP\n'
                             '  2. Use HTTPS\n> ')
            if protocol == '1':
                protocol = 'http://'
                default_port = '80'
            elif protocol == '2':
                protocol = 'https://'
                default_port = '443'
            else:
                protocol = ''
    return protocol, default_port

def confirm_port(port, default_port):
    if not port:
        while not port or not match('\d{1,5}', port):
            port = input('\nNo port specified; use port {}? (Y/n)\n> '.format(default_port))
            if not port or port.lower() == 'y':
                port = default_port
            else:
                port = input('\nPlease specify port:\n> ')
    return port

def acquire_output_dir():
    current_dir = output_dir
    while not path.isdir(current_dir):
        ask_another = False
        create = input('\n{0} does not exist or is not a valid path; attempt to create {0}? (Y/n)\n> '.format(current_dir))
        if not create or create.lower() == 'y':
            try:
                makedirs(current_dir)
                break
            except IOError:
                log.exception('Failed to create {}!'.format(current_dir))
                ask_another = True
        else:
            ask_another = True
        if ask_another:
            current_dir = input('\nPlease specify a different directory or press Enter to use {}:\n> '.format(getcwd()))
            if not current_dir:
                current_dir = getcwd()
                continue
    return current_dir

def confirm_final(top_url):
    print('\nTargeting {} and subdirectories.'.format(top_url))
    if whitelist:
        print('\nOnly following links containing {} and any of the following:'.format(top_url))
        for host in whitelist:
            print(host)
    if blacklist:
        print('\nIgnoring links containing any of the following:')
        for word in blacklist:
            print(word)
    proceed = input('\nProceed? (Y/n)\n> ')
    if not proceed or proceed.lower() == 'y':
        return True
    return False


if __name__ == '__main__':
    parser = ArgumentParser(description='spyder ;D', formatter_class=RawTextHelpFormatter)

    parser.add_argument('target', type=str, help='Desired target, including protocol, port and directory.\n'
                                                 'All subdirectories will be visited.')
    parser.add_argument('-o', '--output_dir', help='Output directory for logs and findings; default: {}'.format(getcwd()))
    parser.add_argument('-w', '--whitelist', nargs='+', help='A series of strings to include as targets.\n'
                                                             'Any pages not containing one of these strings will be skipped.')
    parser.add_argument('-b', '--blacklist', nargs='+', help='A series of strings to exclude as targets.\n'
                                                             'Any pages containing one of these strings will be skipped.')
    parser.add_argument('-k', '--keywords', nargs='+', help='A set of desired keywords of interest.\n'
                                                 'Any pages containing one of these strings will be reported.')
    parser.add_argument('-e', '--max_size_exponent', default=6, type=int, help='Exponent to base 10 for maximum response size calculation.\n'
                                                                               'Responses larger than the calculated size will be skipped.\n'
                                                                               'Default: 6; i.e., responses larger than 10^6 bytes, or 1 MB, will be skipped.')
    parser.add_argument('-t', '--threads', default=5, type=int, help='Maximum number of concurrent threads; default: 5')
    parser.add_argument('-v', '--verbosity', default=2, type=int,
                        help='Specifies which levels of logging messages to show:\r\n'
                             '    1 - Errors only\n'
                             '    2 - Warnings and errors (default)\n'
                             '    3 - Informational messages plus the above\n'
                             '    4 - Debug messages plus the above')
    args = parser.parse_args()

    level_translator = {
        1: ERROR  ,
        2: WARNING,
        3: INFO   ,
        4: DEBUG  ,
    }

    level = WARNING
    if args.verbosity in level_translator:
        level = level_translator[args.verbosity]

    basicConfig(
        level=level,
        format='\r\n%(asctime)s:%(msecs)03d [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        stream=stdout,
    )

    exp = compile('(https?://)?([^:/]+):?(\d{0,5})?(.*)')
    hit = match(exp, args.target)
    if not hit:
        log.error('Invalid target!')
        exit()

    protocol, default_port = confirm_protocol(hit.group(1))
    host  = hit.group(2)
    port  = confirm_port(hit.group(3), default_port)
    scope = hit.group(4)

    log.debug('protocol is {}\r'.format(protocol))
    log.debug('host is {}'    .format(host))
    log.debug('port is {}\r'    .format(port))
    log.debug('scope is {}'   .format(scope))

    top_url = '{}{}{}'.format(protocol, host, scope)

    whitelist = set()
    if args.whitelist:
        whitelist = set(args.whitelist)
    blacklist = set()
    if args.blacklist:
        blacklist = set(args.blacklist)
    keywords = set()
    if args.keywords:
        keywords = set(args.keywords)

    max_size = 10 ** args.max_size_exponent

    global output_dir
    output_dir = args.output_dir
    if not output_dir:
        output_dir = getcwd()
    if not path.isdir(output_dir):
        output_dir = acquire_output_dir()

    if not confirm_final(top_url):
        log.info('User aborted!')
        exit()
    else:
        use_https = False
        if 'https' in protocol:
            use_https = True
        t_opts = TargetOptions(whitelist, blacklist, keywords, max_size)
        target = Target(host, port, use_https, scope, t_opts)
        s_opts = SpyderOptions(max_workers=4)
        spider = Spyder(target, options=s_opts)
        spider.spin()

