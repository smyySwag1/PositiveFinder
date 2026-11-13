# PositiveFinder

Collects **positive, Burmese-only** Facebook posts and comments about Japanese
universities and scholarships, and saves them to CSV files.

## Run it (Windows, PyCharm)

1. Install Google Chrome if you don't have it.
2. Open PyCharm's **Terminal** in this project folder and install the packages:

   ```
   pip install -r requirements.txt
   ```

3. Right-click `fb_burmese_sentiment.py` → **Run**.
4. A Chrome window opens on Facebook. Log in, then go back to PyCharm's
   **Run** window and press **Enter**.
5. Leave it running. Press the red **Stop** button any time - results so far are saved.

## Results

Two files appear in the project folder (open them with Excel):

- `posts_BURMESE_ONLY_POSITIVE_test3_main.csv`
- `comments_BURMESE_ONLY_POSITIVE_test3_main.csv`

They are not uploaded to GitHub (see `.gitignore`), and neither is the
`selenium_profile` folder, which holds your Facebook login.
