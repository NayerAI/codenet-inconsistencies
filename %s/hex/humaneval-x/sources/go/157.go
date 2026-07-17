
// Given the lengths of the three sides of a triangle. Return true if the three
// sides form a right-angled triangle, false otherwise.
// A right-angled triangle is a triangle in which one angle is right angle or
// 90 degree.
// Example:
// RightAngleTriangle(3, 4, 5) == true
// RightAngleTriangle(1, 2, 3) == false
func RightAngleTriangle(a, b, c int) bool {
    return a*a == b*b + c*c || b*b == a*a + c*c || c*c == a*a + b*b
}

