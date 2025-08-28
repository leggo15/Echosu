# echosu

echosu is a **Django** web app that lets the osu! community add crowd-sourced tags to beatmaps and then search for them with powerful operators.

A booru board for osu! maps in a sense with OAuth login, genre fetching, and an open JSON API.

---

### Features

* **osu! OAuth** – Login using your osu account
* **Tagging UI** – create / apply / vote tags; tag-description edit workflow with vote-locking
* **Advanced search** –

  `tech ."awkward aim" -bursts AR<=9.5 BPM>=190`

  operators support inclusion/exclusion, quoted multi-word tags, numeric attribute filters, etc.
* **Beatmap ingest** – paste an ID or osu! URL; metadata & cover pulled from the official API; genres auto-fetched from Last.fm/MusicBrainz
* **Personalised recommendations** – shows maps similar to ones you’ve already tagged (getting axed and replaced by a propper recomendation algorithm)
* **REST API** – read-write endpoints for beatmaps, tags, tag-applications & user profiles, plus a convenience `/api/beatmaps/tags/` aggregator; HMAC-style custom token auth
* **Admin & analytics** – Django admin, request logging middleware, user-stats dashboard

---

### Thanks / Acknowledgements

* osu! team for the public API
* Last.fm & MusicBrainz for music genre data
* Django, DRF, OSSAPI, NumPy, SciPy, NLTK, Better Profanity & friends
* The osu! community for tagging hundreds of beatmaps already!

---

Todo list:

* Merge "Home" and "Find map". -DONE
* Fix the API authentication denied issue. -DONE
* Make sure all search functionallity works propperly. -DONE

  * Make sure tag count when it should show amount of times applied works correctly on all pages. -DONE
  * Make sure tags are sorted propperly. -DONE
  * Tags applied by other users but not current user should be grey and not blue. -DONE
  * Add user made descriptions for tags, initially when a tag is added for the first time. -DONE
* Add ranked/unranked/loved toggles. -DONE
* Add keywords for fav and playcount -DONE
* Mini wiki for how to use search-DONE
* Quick Search on the home page-DONE
* Make documentation for the API -DONE
* Add a write method in the API, users should be able to send in a beatmap ID and tags they wish to apply to said ID. -DONE
* Create a userpage (a new User Stats page where an osu username or userID can be inserted in a field and stats regarding that profile becomes visible, if that user is the currently logged in one then public and private stats show, if its a differnet user, only the public stats show) -DONE

  * Public stats: -DONE

    * What tags are typical for the user's maps, which maps are the most exemplar for the user and which is the most unlike the user to map. (pie chart with most common tags associated with the user's maps)
  * Private Stats:-might drop

    * log of searches done
    * when the user's maps were tagged (line chart time series with tag amount can be sorted by tag)
* "leaderboard" that displays the users who've tagged the most maps. -DONE
* Find the cause for the tag description rearangement bug. -DONE
* Make the recommended maps feature more interesting, add noise to it to keep it from always recomending the same set of maps. -Removed
* Fix so user icon is there even a user has a transparent profile pic -depricated issue
* Fix Audio volume on recommended maps after page 1.-depricated issue
* tag spesific extra metrics when searching (aka if "stream" in query apply +- 10bpm, if "percicion" in query apply +- 1 CS, if "reading" in query apply +- 1 ar) -DONE

  [chrome_RMjJQPyY2L](https://github.com/user-attachments/assets/620d0594-f158-4e4c-ac8f-184ec38e4acf)
