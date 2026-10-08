# Huey
#### Author: Ackeem Ngwenya (a.k.a. Doshi Matoshi)
#### Video Demo: <https://youtu.be/nKi6scJz1MM>
#### Description:

Huey is a Flask web application built around one idea: your skin tone shouldn't be something you have to re-explain to every brand you buy from. A huge number of everyday products are meant to match the wearer's skin. Foundation and concealer are the obvious ones, but the same goes for bandages, hosiery, underwear, hearing aids, tinted sunscreen and even crayons. For many people, especially those with darker skin tones, finding a "nude" or "skin tone" version that actually matches means hunting through many different shops. Huey lets users build a skin profile once and then shows them products from across those categories that are made for their tone.

A visitor lands on Huey's homepage and then signs up. They then set up a skin profile in one of three ways: uploading a photo, taking a selfie with their webcam, or picking their tone directly if they already know it. Tones are expressed on the **Monk Skin Tone (MST) scale**, a public ten-point scale developed by Dr. Ellis Monk with Google. When a photo is used, the server finds the face, corrects the photo's colours for the lighting, measures the skin colour and suggests the three closest MST tones, and the user can accept the suggestion or tap a different swatch. The user also says how reactive their skin is to the sun (low, moderate or high). Once the profile is saved, the **Matches** page shows a scrolling row of product categories and a grid of every product whose MST range includes the user's tone. Users can search by product name, brand, category or sensitivity flag (for example "latex-free" or "fragrance-free"), and those results are filtered to their tone as well.

## Files

**`app.py`** is the Flask application and holds every route. `/` shows the landing page to signed-out visitors and a profile page to signed-in users, with cards for the three ways of setting up a tone. `/signup`, `/login`, `/logout` and `/change_password` handle accounts. Passwords are stored as Werkzeug hashes, emails are lower-cased before they are checked for uniqueness, and changing a password signs the user out. `/setup` shows the tone setup page for the chosen method and, on POST, checks the submitted tone and sensitivity against known values and saves the profile with an `INSERT ... ON CONFLICT DO UPDATE`, so the same code creates a profile or updates it. `/setup/analyze` receives a photo via `fetch()`, passes it to the analysis module and returns JSON. It deliberately saves nothing. `/matches` builds the shop page, choosing a thumbnail for each category from that category's products with a subquery. `/products` handles search and category filters by building a parameterised `WHERE` clause one search word at a time. `/about` explains the project, the MST scale, privacy and limitations.

**`skintone.py`** is the image-processing pipeline and the most technically involved part of the project and where development with Claude code was essentially used. It decodes and downscales the upload, then finds the face. If a MediaPipe Face Landmarker model is present it builds a precise mask of the face oval with the eyes, eyebrows and lips cut out. If not, it falls back to OpenCV's Haar cascade and samples the cheeks and forehead. Next it corrects the white balance, either from a point the user clicked on something white or grey, or automatically from the background with a "shades-of-grey" estimate. The correction is capped so it can't over-correct. Then it converts the skin pixels to the CIELAB colour space, drops the darkest and brightest 15% to ignore shadows and highlights, and takes the median. Finally it finds the nearest MST tones using the CIEDE2000 colour-difference formula. It also reports a confidence level based on how close the top two matches are, and raises a `SkinToneError` with a readable message when a photo can't be used.

**`helpers.py`** contains `apology()`, which renders error pages, and the `login_required` decorator, both adapted from CS50's Finance problem set.

**`import_products.py`** loads `products.csv` (a semicolon-separated catalogue of about 80 real products across nine categories, with MST ranges, sensitivity flags, links, images and prices) into the `products` table. It checks that every MST range is valid and adds the `img_url` and `price` columns to older copies of the database.

**`huey.db`** is the SQLite database. It holds `users`, `profiles` (one row per user, with constraints on the tone and sensitivity), `mst_scale` (the ten tones with their hex and RGB values) and `products`.

**`static/tone_setup.js`** Co-developed with claude Code runs the setup page. In "choose" mode it drives the MST dropdown. In upload and selfie mode it draws the photo or webcam frame to a `<canvas>`, lets the user click a white point, sends the image to `/setup/analyze`, shows the suggested swatches and stops the form from being submitted until a tone has been chosen. **`static/style.css`** contains all custom styling, including the landing-page gallery animation, which is turned off for users who prefer reduced motion.

**`templates/`** holds the Jinja templates: `layout.html` (the shared navbar and Bootstrap setup), `landing.html`, `index.html`, `tone.html`, `matches.html`, `products.html`, `about.html`, the account forms (`login.html`, `signup.html`, `change_password.html`) and `apology.html`. `product_card.html` and `search_bar.html` are partials included by both the matches and products pages so the two stay consistent.

## Design choices

**Monk scale instead of Fitzpatrick.** The Fitzpatrick scale is the usual dermatological standard, but it was designed to classify how skin reacts to the sun, not to describe colour, and it has only six types, which are especially coarse for darker skin. The Monk scale was designed for representing colour across the full range of skin tones, so I used it for matching and kept the separate question about sun sensitivity for the Fitzpatrick-style information.

**Analyse on the server, never store the photo.** I considered measuring colour in the browser, but OpenCV, scikit-image and MediaPipe made reliable face detection and colour science far easier in Python. To respect privacy, the photo is analysed in memory and thrown away. Only the chosen MST tone is saved. Analysis also goes through a separate JSON endpoint instead of the profile form, so the user always sees and confirms the suggestion before anything is saved.

**Colour maths.** My first attempt averaged raw RGB values, which was thrown off by warm indoor lighting and shiny highlights. Switching to CIELAB, using the median of the middle of the brightness range, white-balancing first and comparing with CIEDE2000 (which is designed to match how people perceive colour differences) made the results noticeably more stable. Because a photo can only give an estimate, the app always shows the top three matches and lets the user override them.

**Ranges instead of exact matches.** Many products, such as a "Medium" bandage, cover several tones, so each product stores an `mst_range_min` and `mst_range_max` rather than a single tone. Matching is then a simple range check in SQL.

**CSV for the catalogue.** I keep products in a spreadsheet-friendly CSV and re-import it, instead of editing SQL by hand, so the catalogue is easy to grow and check.

## Running it

```
pip install -r requirements.txt
python import_products.py
flask run
```
