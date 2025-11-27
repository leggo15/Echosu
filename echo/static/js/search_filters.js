// Search page filters: jQuery UI range slider for star rating
$(function() {
  // Layered preset hover behavior with class toggles for cross-browser support
  var slider = document.querySelector('.preset-slider');
  if (slider) {
    var farm = slider.querySelector('.preset-button--farm');
    var fav = slider.querySelector('.preset-button--favorites');
    if (farm && fav) {
      var clear = function(){ slider.classList.remove('hover-farm', 'hover-favorites'); };
      farm.addEventListener('mouseenter', function(){ slider.classList.add('hover-farm'); slider.classList.remove('hover-favorites'); });
      fav.addEventListener('mouseenter', function(){ slider.classList.add('hover-favorites'); slider.classList.remove('hover-farm'); });
      slider.addEventListener('mouseleave', clear);
      // Touch support: tap toggles between the two states
      farm.addEventListener('touchstart', function(){ slider.classList.add('hover-farm'); slider.classList.remove('hover-favorites'); }, {passive: true});
      fav.addEventListener('touchstart', function(){ slider.classList.add('hover-favorites'); slider.classList.remove('hover-farm'); }, {passive: true});
    }
  }
  var filtersForm = document.querySelector('form.beatmap-form');
  if (filtersForm) {
    var modeSelect = filtersForm.querySelector('#mode');
    if (modeSelect) {
      modeSelect.addEventListener('change', function(){
        if (filtersForm.requestSubmit) {
          filtersForm.requestSubmit();
        } else {
          filtersForm.submit();
        }
      });
    }
  }

  var $slider = $("#star-rating-slider");
  if (!$slider.length) return;
  $slider.slider({
    range: true,
    min: 0,
    max: 15,
    step: 0.1,
    values: [
      parseFloat($("#star_min").val()) || 0,
      (function(){
        var v = parseFloat($("#star_max").val());
        if (isNaN(v)) return 15;
        return v >= 15 ? 15 : v;
      })()
    ],
    slide: function(event, ui) {
      $("#star_min").val(ui.values[0]);
      if (ui.values[1] >= 15) {
        $("#star_max").val(15);
        $("#star-rating-max").text("15+");
      } else {
        $("#star_max").val(ui.values[1]);
        $("#star-rating-max").text(ui.values[1].toFixed(1));
      }
      $("#star-rating-min").text(ui.values[0].toFixed(1));
    },
    change: function() {
      var min = parseFloat($("#star_min").val()) || 0;
      var max = parseFloat($("#star_max").val()) || 15;
      $("#star-rating-min").text(min.toFixed(1));
      $("#star-rating-max").text(max >= 15 ? "15+" : max.toFixed(1));
    }
  });

  var initial_min = parseFloat($("#star_min").val());
  var initial_max = parseFloat($("#star_max").val());
  $("#star-rating-max").text(initial_max >= 15 || isNaN(initial_max) ? "15+" : initial_max.toFixed(1));
  $("#star-rating-min").text(isNaN(initial_min) ? "0.0" : initial_min.toFixed(1));

  $("#star_min, #star_max").on('change', function() {
    var min = parseFloat($("#star_min").val()) || 0;
    var max = parseFloat($("#star_max").val()) || 15;
    $("#star-rating-min").text(min.toFixed(1));
    $("#star-rating-max").text(max >= 15 ? "15+" : max.toFixed(1));
    $slider.slider("values", [min, max >= 15 ? 15 : max]);
  });
});

