from commercelens import extract_listing


if __name__ == "__main__":
    result = extract_listing("https://books.toscrape.com/catalogue/page-1.html")
    print(result.model_dump_json(indent=2))
