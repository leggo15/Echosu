[chrome_RMjJQPyY2L](https://github.com/user-attachments/assets/620d0594-f158-4e4c-ac8f-184ec38e4acf)

Todo list for dev:

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


* Create a userpage (a new User Stats page where an osu username or userID can be inserted in a field and stats regarding that profile becomes visible, if that user is the currently logged in one then public and private stats show, if its a differnet user, only the public stats show)

  * Public stats:

    * What tags are typical for the user's maps, which maps are the most exemplar for the user and which is the most unlike the user to map. (pie chart with most common tags associated with the user's maps)
    * list of maps the user has tagged, and their most used tags
  * Private Stats:

    * log of searches done
    * when the user's maps were tagged (line chart time series with tag amount can be sorted by tag)


* "leaderboard" that displays the users who've tagged the most maps.
* Find the cause for the tag description rearangement bug.
* Make the recommended maps feature more interesting, add noise to it to keep it from always recomending the same set of maps.
* Fix so user icon is there even a user has a transparent profile pic
* Fix Audio volume on recommended maps after page 1.
* Add keywords for amount of tags added to map
