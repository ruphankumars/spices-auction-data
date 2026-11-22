"""The text of the Spices Board's e-auction schedule circulars, for the Cardamom server.

The server's own reading (tesseract in Node) runs out of memory on Render, so the
circular is read here instead and kept as schedule/<circular key>.txt, the key
being the server's circularKey(): the file name, decoded, lower case.
"""
import os, re, subprocess, sys, tempfile, urllib.parse, requests

PAGE = 'https://www.indianspices.com/trade/trade-notifications.html'
UA = {'User-Agent': 'CardamomMarketReport/1.0 (+schedule)'}


def key(url):
    name = urllib.parse.unquote(url.split('?')[0].split('/')[-1])
    return re.sub(r'\s+', ' ', name.lower()).strip()


def text_of(pdf):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'c.pdf')
        open(path, 'wb').write(pdf)
        text = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True).stdout
        if re.search(r'SCHEDULE FOR CONDUCTING CARDAMOM AUCTIONS', text, re.I) and re.search(r'\d{2}/\d{2}/\d{4}', text):
            return text
        subprocess.run(['pdftoppm', '-r', '200', '-gray', '-png', path, os.path.join(d, 'p')], check=True)
        pages = sorted(f for f in os.listdir(d) if f.endswith('.png'))
        return '\n'.join(subprocess.run(['tesseract', os.path.join(d, f), 'stdout', '--psm', '4'],
                                        capture_output=True, text=True).stdout for f in pages)


def main():
    html = requests.get(PAGE, headers=UA, timeout=30).text
    seen = set()
    for href, label in re.findall(r'href\s*=\s*["\']([^"\']+\.pdf)["\'][^>]*>([\s\S]*?)</a>', html, re.I):
        hay = (href + ' ' + re.sub(r'<[^>]+>', ' ', label)).lower()
        if 'schedule' not in hay or not re.search(r'puttady|puttadi|bodinaykanur|bodinayakanur|e-?auction', hay):
            continue
        url = urllib.parse.urljoin(PAGE, href).replace(' ', '%20')
        k = key(url)
        out = os.path.join('schedule', k + '.txt')
        if k in seen or os.path.exists(out):
            continue
        seen.add(k)
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            open(out, 'w').write(text_of(r.content))
            print('read', k)
        except Exception as e:  # one bad link does not stop the others
            print('failed', k, e, file=sys.stderr)


if __name__ == '__main__':
    main()
