class Vec3:
    def __init__(self, x=0, y=0, z=0):
        self.x = x
        self.y = y
        self.z = z

    def __add__(self, rhs):
        c = self.clone()
        c += rhs
        return c

    def __iadd__(self, rhs):
        self.x += rhs.x
        self.y += rhs.y
        self.z += rhs.z
        return self

    def length(self):
        return self.lengthSqr() ** 0.5

    def lengthSqr(self):
        return self.x * self.x + self.y * self.y + self.z * self.z

    def __mul__(self, k):
        c = self.clone()
        c *= k
        return c

    def __imul__(self, k):
        self.x *= k
        self.y *= k
        self.z *= k
        return self

    def clone(self):
        return Vec3(self.x, self.y, self.z)

    def __neg__(self):
        return Vec3(-self.x, -self.y, -self.z)

    def __sub__(self, rhs):
        return self.__add__(-rhs)

    def __isub__(self, rhs):
        return self.__iadd__(-rhs)

    def __repr__(self):
        return f"Vec3({self.x},{self.y},{self.z})"

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def _map(self, func):
        self.x = func(self.x)
        self.y = func(self.y)
        self.z = func(self.z)

    def __cmp__(self, rhs):
        dx = self.x - rhs.x
        if dx != 0:
            return dx
        dy = self.y - rhs.y
        if dy != 0:
            return dy
        dz = self.z - rhs.z
        if dz != 0:
            return dz
        return 0

    def __eq__(self, rhs):
        if self.x == rhs.x and self.y == rhs.y and self.z == rhs.z:
            return True
        return False

    def iround(self):
        self._map(lambda v: int(v + 0.5))

    def ifloor(self):
        self._map(int)

    def rotateLeft(self):
        self.x, self.z = self.z, -self.x

    def rotateRight(self):
        self.x, self.z = -self.z, self.x

    @staticmethod
    def y_axis(n=1):
        return Vec3(0, n, 0)

    @staticmethod
    def up(n=1):
        return Vec3.y_axis(n)

    @staticmethod
    def down(n=1):
        return Vec3.y_axis(-n)


def testVec3():
    # Note: It's not testing everything

    # 1.1 Test initialization
    it = Vec3(1, -2, 3)
    assert it.x == 1
    assert it.y == -2
    assert it.z == 3

    assert it.x != -1
    assert it.y != +2
    assert it.z != -3

    # 2.1 Test cloning and equality
    clone = it.clone()
    assert it == clone
    it.x += 1
    assert it != clone

    # 3.1 Arithmetic
    a = Vec3(10, -3, 4)
    b = Vec3(-7, 1, 2)
    c = a + b
    assert c - a == b
    assert c - b == a
    assert a + a == a * 2

    assert a - a == Vec3(0, 0, 0)
    assert a + (-a) == Vec3(0, 0, 0)

    # Test repr
    repr_str = repr(it)
    e = Vec3(it.x, it.y, it.z)
    assert repr(e) == repr_str

    assert it.length() == (1**2 + (-2) ** 2 + 3**2) ** 0.5
    assert it.lengthSqr() == 1**2 + (-2) ** 2 + 3**2


if __name__ == "__main__":
    testVec3()
