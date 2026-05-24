# CarMax Feasibility Spike — Results

**Date:** 2026-05-23
**Time-box:** ~40 min
**Decision:** GO-CARMAX

## CarMax findings

- **Real API endpoint(s):** No separate JSON API. Vehicle data is **server-side rendered** into the HTML page as an inline `const cars = [...]` JavaScript array. The browser-facing URL is:
  ```
  https://www.carmax.com/cars/all?zip=90405&distance=25&priceMin=5000&priceMax=12000&transmission=Automatic
  ```
  Supported query params confirmed: `zip`, `distance`, `priceMin`, `priceMax`, `transmission` (values: `Automatic`, `Manual`).

- **Required headers:**
  ```
  User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
  Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8
  Accept-Language: en-US,en;q=0.9
  Accept-Encoding: gzip, deflate, br
  sec-ch-ua: "Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"
  sec-ch-ua-mobile: ?0
  sec-ch-ua-platform: "macOS"
  Sec-Fetch-Dest: document
  Sec-Fetch-Mode: navigate
  Sec-Fetch-Site: none
  Upgrade-Insecure-Requests: 1
  ```
  HTTP/2 is required (`httpx[http2]`). The full Sec-Fetch-* + sec-ch-ua headers are what pass Akamai's bot check. Minimal headers (just User-Agent) → 403.

- **Cookies needed:** None. Session cookies are not required for the initial SSR response.

- **httpx replay result:** **200 with 24 listings** — confirmed working without a browser.

- **Working snippet:**
  ```python
  import httpx, re, json

  HEADERS = {
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
      "Accept-Encoding": "gzip, deflate, br",
      "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
      "sec-ch-ua-mobile": "?0",
      "sec-ch-ua-platform": '"macOS"',
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
      "Sec-Fetch-Site": "none",
      "Upgrade-Insecure-Requests": "1",
  }

  def fetch_carmax(zip_code, distance=25, price_min=5000, price_max=12000, transmission="Automatic"):
      params = {
          "zip": zip_code, "distance": str(distance),
          "priceMin": str(price_min), "priceMax": str(price_max),
          "transmission": transmission,
      }
      with httpx.Client(follow_redirects=True, timeout=20, headers=HEADERS, http2=True) as client:
          resp = client.get("https://www.carmax.com/cars/all", params=params)
      resp.raise_for_status()
      return _extract_cars(resp.text)

  def _extract_cars(html):
      for block in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
          if 'const cars = [' not in block:
              continue
          start = block.index('const cars = [') + len('const cars = ')
          depth, i = 0, start
          while i < len(block):
              ch = block[i]
              if ch == '[': depth += 1
              elif ch == ']':
                  depth -= 1
                  if depth == 0:
                      return json.loads(block[start:i+1])
              i += 1
      return []
  ```

- **Sample response shape (71 fields per vehicle):**
  ```json
  {
    "stockNumber": 27735640,
    "vin": "2C3CDXGJ8NH226089",
    "year": 2022,
    "make": "Dodge",
    "model": "Charger",
    "trim": "Scat Pack",
    "body": "4D Sedan",
    "basePrice": 43998.0,
    "originalPrice": null,
    "hasPriceDrop": false,
    "mileage": 29090,
    "transmission": "Automatic",
    "storeId": 7124,
    "storeName": "Canoga Park",
    "stateAbbreviation": "CA",
    "distance": 16.1,
    "exteriorColor": "Silver",
    "interiorColor": "Black",
    "mpgCity": 15,
    "mpgHighway": 24,
    "cylinders": 8,
    "driveTrain": "Rear Wheel Drive",
    "engineSize": "6.4L",
    "horsepower": 485,
    "features": ["Power Locks", "..."],
    "heroImageUrl": "https://img2.carmax.com/assets/27735640/hero.jpg?width=400&height=300",
    "isSaleable": true,
    "isTransferable": true,
    "transferFee": 0.0
  }
  ```
  Total results for this query: **1,558 vehicles**. SSR bakes **24 per page**. Pagination is pure SPA (no server-side `?page=N` support) — each httpx fetch returns the first 24 results. Multiple queries with different filters (make, model, year ranges) can be used to cover more inventory.

## Fallback findings

- **Cars.com:** Not tested — CarMax works.
- **CarGurus:** Not tested — CarMax works.

## Recommendation for M2

Implement the CarMax fetcher using `httpx[http2]` against `https://www.carmax.com/cars/all` with the Sec-Fetch-* + sec-ch-ua headers above. Parse the `const cars = [...]` block from the SSR HTML using bracket-matching. Each fetch returns 24 richly-structured listings; chain multiple filter combinations (by make/model/year) to retrieve broader inventory slices. No API key, no cookies, no browser required.

## Known fragility

1. **Header fingerprint drift:** Akamai Bot Manager will eventually update its challenge. The specific set of `sec-ch-ua` and `Sec-Fetch-*` headers that pass today may need updating in 3-6 months when Akamai updates its bot signatures. Minimal headers (just User-Agent) already fail today.
2. **SSR payload may shrink/disappear:** CarMax could move to full client-side rendering or lazy-load the `const cars` array via a separate XHR call in a future deploy. Monitor by asserting `'const cars = ['` is present in the response.
3. **24-per-page SSR ceiling:** No server-side pagination discovered. Deep inventory access requires multiple filter-narrowed queries (make/model/year/price band combinations).
4. **Rate limiting:** Not tested at volume. Aggressive polling (sub-second requests) will likely trigger 429s or Akamai blocks. Add a 1-2s delay between requests in production.
