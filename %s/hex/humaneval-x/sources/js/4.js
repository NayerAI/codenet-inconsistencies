/* For a given list of input numbers, calculate Mean Absolute Deviation
  around the mean of this dataset.
  Mean Absolute Deviation is the average absolute difference between each
  element and a centerpoint (mean in this case):
  MAD = average | x - x_mean |
  >>> meanAbsoluteDeviation([1.0, 2.0, 3.0, 4.0])
  1.0
  */
const meanAbsoluteDeviation = (numbers) => {
  var mean = numbers.reduce((prev, item) => {
    return prev + item;
  }, 0) / numbers.length;
  return numbers.reduce((prev, item) => {
    return prev + Math.abs(item - mean);
  }, 0) / numbers.length;

}

