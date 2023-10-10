from django.contrib import admin
from .models import Article, Comment


# class CommentInLine(admin.StackedInline):
#     model = Comment
#     extra = 1


class CommentInLine(admin.TabularInline):
    model = Comment
    extra = 1  # default = 3


class ArticleAdmin(admin.ModelAdmin):
    inlines = [
        CommentInLine,
    ]


admin.site.register(Article, ArticleAdmin)
admin.site.register(Comment)
