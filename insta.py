import json
import instaloader

USERNAME_TO_FETCH = 'ica_supermarket_hansa'
SESSION_USERNAME = 'bamba_bot'

L = instaloader.Instaloader()

L.load_session_from_file(SESSION_USERNAME)

profile = instaloader.Profile.from_username(L.context, USERNAME_TO_FETCH)

posts_data = []

for post in profile.get_posts():
    posts_data.append({
        'shortcode': post.shortcode,
        'caption': post.caption,
        'date': post.date_utc.isoformat(),
        'url': post.url,
    })
    break  # only latest post

with open('latest_post.json', 'w', encoding='utf-8') as f:
    json.dump(posts_data, f, ensure_ascii=False, indent=2)

print("Saved latest post to latest_post.json")