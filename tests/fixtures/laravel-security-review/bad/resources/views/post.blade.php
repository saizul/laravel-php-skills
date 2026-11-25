<h1>{{ $post->title }}</h1>
{!! $post->body_html !!}
<p>Search: {!! request('q') !!}</p>
<form method="POST">{!! csrf_field() !!}</form>
{{-- {!! $ignored !!} in a Blade comment --}}
{!! $posts->links() !!}
