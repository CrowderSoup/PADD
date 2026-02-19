/**
 * Creates an EasyMDE instance with LCARS theme defaults.
 *
 * @param {HTMLTextAreaElement} element - The textarea to enhance.
 * @param {Object} [overrides] - Options to merge over the defaults.
 * @returns {EasyMDE}
 */
function createLcarsEditor(element, overrides) {
  var defaults = {
    element: element,
    spellChecker: false,
    status: false,
    autoDownloadFontAwesome: false,
    toolbar: ['bold', 'italic', 'heading', '|', 'quote', 'unordered-list', 'ordered-list', '|', 'link', 'image', '|', 'preview'],
    insertTexts: {
      link: ['[', '](url)'],
      image: ['![', '](url)'],
    },
  };
  var options = Object.assign({}, defaults, overrides);
  var editor = new EasyMDE(options);
  editor.codemirror.getInputField().setAttribute('spellcheck', 'true');
  return editor;
}
