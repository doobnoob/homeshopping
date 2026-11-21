# Household Price Tracker – setup (about 20 minutes)

You'll use three free services: **Supabase** (shared database + logins), **GitHub Pages** (hosts the app) and **GitHub Actions** (runs the daily price check).

## 1. Supabase
1. Create a project at supabase.com (pick a region close to you, e.g. Sydney).
2. **SQL Editor → New query**, paste the contents of `supabase.sql`, click **Run**.
3. **Authentication → Providers → Email**: turn **off** "Allow new users to sign up" (this keeps strangers out).
4. **Authentication → Users → Add user**: create an account (email + password) for each household member.
5. **Project Settings → API**: note the **Project URL**, the **anon public** key and the **service_role** key. Keep service_role secret.

## 2. GitHub
1. Create a new GitHub repository and upload everything in this folder (including the hidden `.github` folder).
2. Open `index.html`, replace `YOUR_SUPABASE_URL` and `YOUR_SUPABASE_ANON_KEY` with your values and commit.
3. **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `SUPABASE_URL` = your Project URL
   - `SUPABASE_SERVICE_KEY` = your service_role key
4. **Settings → Pages**: Source = "Deploy from a branch", branch `main`, folder `/ (root)`. After a minute your app is at `https://<username>.github.io/<repo>/`.
5. **Actions → Check prices → Run workflow** to test it. After that it runs daily.

## 3. Use it
Open the Pages link on every phone/PC, sign in, and use "Add to Home Screen" for an app-like icon. Add items with a product URL. Open an item to see history, log prices by hand, or set scraper options.

## When a price isn't found
The item shows "⚠ auto-check failed". Open it → **Scraper settings**:
- Right-click the price on the shop's page → Inspect, copy a CSS selector (e.g. `.price .amount`), paste it in.
- Tick **Needs JavaScript** if the price only appears after the page loads.
- Some shops block automated visits. For those, keep logging prices by hand.

## Good to know
- A price row is only added when the price **changes**, so history shows each change rather than daily duplicates.
- GitHub pauses scheduled workflows after 60 days with no repo activity; re-enable under the Actions tab if that happens.
- The repository can be public: the anon key is meant to be public, and the database only answers to signed-in household members. Never put the service_role key in any file.
- Check each shop's terms before automated checking. The script makes one request per item per day.
