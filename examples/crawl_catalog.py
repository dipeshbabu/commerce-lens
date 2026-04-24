from commercelens import crawl_catalog


if __name__ == "__main__":
    result = crawl_catalog("https://books.toscrape.com/catalogue/page-1.html", max_pages=2)
    print(result.model_dump_json(indent=2))
