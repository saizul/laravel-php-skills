<h1>{{ $post->title }}</h1>
<div>{{ $post->body }}</div>
<form method="POST">@csrf</form>
{!! $posts->links() !!}
