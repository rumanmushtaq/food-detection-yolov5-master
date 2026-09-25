var el = x => document.getElementById(x);
var detectBtn = document.querySelector("#analyze-button");

function showPicker() {
  $("#file-input").click();
}

function clearContent() {
  $('#image-display').empty(); // removes upload img
  $('#upload-label').empty(); //removes upload img's filename
  $('#result-content').remove();   //remove result div (image + labels ...)
}

// Show uploaded image or video
function showPicked(input) {

  const extension = input.files[0].name.split(".").pop().toLowerCase();
  const reader = new FileReader();

  reader.onload = function(e) {
    clearContent();
    el("upload-label").textContent = input.files[0].name;
    var file_url = e.target.result

    if (extension === "mp4" || extension === 'avi' || extension === '3gpp' || extension === '3gp'){
      var container = document.getElementById('image-display');
      var video = document.createElement('video');
      video.id = 'user-video';
      video.autoplay = true;
      video.controls = true;
      var source = document.createElement('source');
      source.id = 'user-source';
      source.src = file_url;
      video.appendChild(source);
      container.appendChild(video);
      video.load();
      video.play();
    }

    else if(extension === "jpg" || extension === "jpeg" || extension === "png"){
      var container = document.getElementById('image-display');
      var img = document.createElement('img');
      img.id = 'user-image';
      img.src = file_url;
      img.style.cssText = 'display:block;margin-left:auto;margin-right:auto;max-width:100%;height:auto';
      container.appendChild(img);
    }
  
  };

  detectBtn.removeAttribute("disabled");

  reader.readAsDataURL(input.files[0]);
}

window.onload = function(){
  $('#threshold-range').on('input', function() {
    $('#threshold-text span').html(this.value);
    threshold = $('#threshold-range').val() / 100;
  });

  $('#confidence-range').on('input', function() {
    $('#confidence-text span').html(this.value);
    confidence = $('#confidence-range').val() / 100;
  });

}