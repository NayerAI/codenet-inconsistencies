/* For a given string, flip lowercase characters to uppercase and uppercase to lowercase.
  >>> flipCase('Hello')
  'hELLO'
  */
const flipCase = (string) => {
  return string.split('')
          .map(x => (x.toUpperCase() == x ? x.toLowerCase() : x.toUpperCase()))
          .join('');
}

