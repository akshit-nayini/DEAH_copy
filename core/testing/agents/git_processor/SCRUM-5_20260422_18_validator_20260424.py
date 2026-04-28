
-- adde comment
def greet(name):
    return f"Hello, {name}!"

def add(a, b):
    return a + b

def main():
    user_name = "Harish"
    x, y = 5, 10

    greeting = greet(user_name)
    result = add(x, y)

    print(greeting)
    print(f"Sum of {x} and {y} is {result}")

if __name__ == "__main__":
    main()
